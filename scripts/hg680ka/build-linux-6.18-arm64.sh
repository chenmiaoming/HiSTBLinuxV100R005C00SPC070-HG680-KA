#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/out/hg680ka-linux-6.18-arm64}"

LINUX_VERSION=6.18.46
LINUX_ARCHIVE="linux-${LINUX_VERSION}.tar.xz"
LINUX_URL="https://cdn.kernel.org/pub/linux/kernel/v6.x/${LINUX_ARCHIVE}"
LINUX_SHA256="f5d44b93808b02cc2969c5404ba081d97523719c9fd2ba2de6db318b4141cca0"
CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}"
KERNEL_LOAD_ADDR=0x00200000

DTS="$ROOT/linux-6.18/hg680ka-minimal.dts"
SMP_INSTRUMENT="$ROOT/linux-6.18/instrument-secondary.py"
WORK="$OUT/work"
SRC="$WORK/linux-${LINUX_VERSION}"
KOUT="$OUT/kernel"
ART="$OUT/artifacts"
ATF_OUT="$OUT/atf-smoke"

rm -rf "$OUT"
mkdir -p "$WORK" "$KOUT" "$ART"

for tool in curl tar xz dtc mkimage sha256sum make gcc readelf python3; do
	command -v "$tool" >/dev/null || {
		echo "missing host tool: $tool" >&2
		exit 1
	}
done
for tool in gcc ld objcopy; do
	command -v "${CROSS_COMPILE}${tool}" >/dev/null || {
		echo "missing AArch64 cross tool: ${CROSS_COMPILE}${tool}" >&2
		exit 1
	}
done

test -s "$DTS"
test -s "$SMP_INSTRUMENT"

printf 'Fetching Linux %s from kernel.org...\n' "$LINUX_VERSION"
curl --fail --location --retry 3 --output "$WORK/$LINUX_ARCHIVE" "$LINUX_URL"
printf '%s  %s\n' "$LINUX_SHA256" "$WORK/$LINUX_ARCHIVE" | sha256sum -c -

tar -C "$WORK" -xf "$WORK/$LINUX_ARCHIVE"
test -d "$SRC"

# Temporary hardware diagnostic: mark the secondary MMU-off path directly via
# the physical PL011 so we can locate a stall before normal printk is usable.
# The injector checks every source anchor matches exactly once; unlike a fuzzy
# patch this fails deterministically if Linux source layout changes.
python3 "$SMP_INSTRUMENT" "$SRC/arch/arm64/kernel/head.S"

grep -F 'hg680ka_uart_marker 0x41' "$SRC/arch/arm64/kernel/head.S"
grep -F 'hg680ka_uart_marker 0x42' "$SRC/arch/arm64/kernel/head.S"
grep -F 'hg680ka_uart_marker 0x43' "$SRC/arch/arm64/kernel/head.S"
grep -F 'hg680ka_uart_marker 0x44' "$SRC/arch/arm64/kernel/head.S"

printf 'Building Linux %s ARM64 defconfig...\n' "$LINUX_VERSION"
make -C "$SRC" O="$KOUT" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" defconfig

# Keep the diagnostic kernel config unchanged while isolating the SMP failure.
# Once low-level SMP is stable this generic config will be replaced by the
# board-specific hg680ka_arm64_minimal_defconfig.
"$SRC/scripts/config" --file "$KOUT/.config" \
	-e SMP \
	-e ARM_PSCI_FW \
	-e ARM_GIC \
	-e SERIAL_AMBA_PL011 \
	-e SERIAL_AMBA_PL011_CONSOLE \
	-e KVM

make -C "$SRC" O="$KOUT" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" olddefconfig
make -C "$SRC" O="$KOUT" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" \
	-j"$(nproc)" Image

IMAGE="$KOUT/arch/arm64/boot/Image"
test -s "$IMAGE"

# Build two DTBs from the same hardware description. The SMP variant preserves
# the normal four-CPU boot. The maxcpus=1 variant bypasses secondary CPU bring-up
# and tells us whether CPU0 can continue through init with its timer/IRQ path.
DTB_SMP="$ART/hi3798mv310-hg680ka-smpdiag.dtb"
dtc -I dts -O dtb -o "$DTB_SMP" "$DTS"
test -s "$DTB_SMP"

MAX1_DTS="$WORK/hg680ka-maxcpus1.dts"
sed 's/panic=-1"/panic=-1 maxcpus=1 initcall_debug"/' "$DTS" > "$MAX1_DTS"
grep -F 'maxcpus=1 initcall_debug' "$MAX1_DTS"
DTB_MAX1="$ART/hi3798mv310-hg680ka-maxcpus1.dtb"
dtc -I dts -O dtb -o "$DTB_MAX1" "$MAX1_DTS"
test -s "$DTB_MAX1"

# Factory load_fip() expects BL33 as a legacy ARM64 uImage immediately followed
# by its DTB. Keep the uImage payload 8-byte aligned because factory ARM32
# libfdt performs native word accesses to the trailing FDT header.
PADDED_IMAGE="$WORK/Image.padded"
cp "$IMAGE" "$PADDED_IMAGE"
image_size=$(stat -c %s "$IMAGE")
padded_size=$(( (image_size + 7) & ~7 ))
truncate -s "$padded_size" "$PADDED_IMAGE"

# Linux 6.18 requires the physical kernel image base to be 2 MiB aligned.
UIMAGE="$ART/Image-6.18.46.uImage"
mkimage -A arm64 -O linux -T kernel -C none \
	-a "$KERNEL_LOAD_ADDR" -e "$KERNEL_LOAD_ADDR" \
	-n 'HG680KA Linux 6.18.46 ARM64' \
	-d "$PADDED_IMAGE" "$UIMAGE"
(( $(stat -c %s "$UIMAGE") % 8 == 0 ))

# Reuse the hardware-proven vendor TF-A build path. This also asserts BL31 is
# linked at factory Fastboot's observed RVBAR address 0x08020000.
bash "$ROOT/scripts/hg680ka/build-arm64-atf-smoke.sh" "$ATF_OUT"
BL31="$ATF_OUT/artifacts/bl31.bin"
BL31_ELF="$ATF_OUT/artifacts/bl31.elf"
FIP_CREATE="$ATF_OUT/fip_create"
test -s "$BL31"
test -s "$BL31_ELF"
test -x "$FIP_CREATE"

pack_fip() {
	local dtb="$1"
	local stem="$2"
	local bl33="$WORK/bl33-${stem}.bin"
	local fip="$ART/hg680ka-linux-${LINUX_VERSION}-${stem}.fip"
	local dump="$ART/FIP-DUMP-${stem}.txt"

	cat "$UIMAGE" "$dtb" > "$bl33"
	"$FIP_CREATE" --bl31 "$BL31" --bl33 "$bl33" "$fip"
	"$FIP_CREATE" --dump "$fip" | tee "$dump"
	printf '%s BL33 packed size: %u bytes\n' "$stem" "$(stat -c %s "$bl33")" | tee -a "$ART/BUILD-INFO.txt"
}

: > "$ART/BUILD-INFO.txt"
pack_fip "$DTB_MAX1" maxcpus1
pack_fip "$DTB_SMP" smpdiag

cp "$IMAGE" "$ART/Image-6.18.46"
cp "$KOUT/.config" "$ART/linux-6.18.46.config"
cp "$BL31" "$ART/bl31.bin"
cp "$BL31_ELF" "$ART/bl31.elf"
cp "$DTS" "$ART/hg680ka-minimal.dts"
cp "$SMP_INSTRUMENT" "$ART/instrument-secondary.py"

printf 'Linux raw Image size: %u bytes\n' "$image_size" | tee -a "$ART/BUILD-INFO.txt"
printf 'Linux padded size:    %u bytes\n' "$padded_size" | tee -a "$ART/BUILD-INFO.txt"
printf 'Kernel load address:  0x%08x\n' "$((KERNEL_LOAD_ADDR))" | tee -a "$ART/BUILD-INFO.txt"
printf 'SMP DTB size:         %u bytes\n' "$(stat -c %s "$DTB_SMP")" | tee -a "$ART/BUILD-INFO.txt"
printf 'maxcpus=1 DTB size:   %u bytes\n' "$(stat -c %s "$DTB_MAX1")" | tee -a "$ART/BUILD-INFO.txt"
printf 'Linux version:        %s\n' "$LINUX_VERSION" | tee -a "$ART/BUILD-INFO.txt"
printf 'Kernel source SHA256: %s\n' "$LINUX_SHA256" | tee -a "$ART/BUILD-INFO.txt"

(
	cd "$ART"
	sha256sum \
		Image-6.18.46 \
		Image-6.18.46.uImage \
		hi3798mv310-hg680ka-smpdiag.dtb \
		hi3798mv310-hg680ka-maxcpus1.dtb \
		linux-6.18.46.config \
		bl31.bin \
		bl31.elf \
		hg680ka-linux-6.18.46-maxcpus1.fip \
		hg680ka-linux-6.18.46-smpdiag.fip \
		> SHA256SUMS
	sha256sum -c SHA256SUMS
)

printf '\nHG680-KA Linux 6.18 ARM64 diagnostic artifacts:\n'
ls -lh "$ART"
printf '\nBoard tests (RAM/USB only):\n'
printf '  1) fatload usb 0:1 0x02000000 hg680ka-linux-%s-maxcpus1.fip\n' "$LINUX_VERSION"
printf '     bootm 0x02000000\n'
printf '  2) fatload usb 0:1 0x02000000 hg680ka-linux-%s-smpdiag.fip\n' "$LINUX_VERSION"
printf '     bootm 0x02000000\n'
