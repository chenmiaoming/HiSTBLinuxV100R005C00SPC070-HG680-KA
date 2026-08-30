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
ATF_SMP_INSTRUMENT="$ROOT/linux-6.18/instrument-atf-smpen.py"
ATF_PM="$ROOT/source/kernel/arm-trusted-firmware/plat/hisilicon/hi3798mv310/hisi_pm.c"
WORK="$OUT/work"
SRC="$WORK/linux-${LINUX_VERSION}"
KOUT="$OUT/kernel"
ART="$OUT/artifacts"
ATF_OUT="$OUT/atf-smoke"

rm -rf "$OUT"
mkdir -p "$WORK" "$KOUT" "$ART"

for tool in curl tar xz dtc mkimage sha256sum make gcc readelf python3 nproc; do
	command -v "$tool" >/dev/null || {
		echo "missing host tool: $tool" >&2
		exit 1
	}
done
for tool in gcc ld objcopy objdump nm; do
	command -v "${CROSS_COMPILE}${tool}" >/dev/null || {
		echo "missing AArch64 cross tool: ${CROSS_COMPILE}${tool}" >&2
		exit 1
	}
done

test -s "$DTS"
test -s "$SMP_INSTRUMENT"
test -s "$ATF_SMP_INSTRUMENT"
test -s "$ATF_PM"

printf 'Build host online CPUs: %s\n' "$(nproc)"
printf 'Fetching Linux %s from kernel.org...\n' "$LINUX_VERSION"
# kernel.org/CDN occasionally resets GitHub-hosted runner HTTP/2 streams.
# Force HTTP/1.1 and retry transport errors as well as HTTP failures.
curl --http1.1 --fail --location --retry 5 --retry-all-errors --retry-delay 2 \
	--output "$WORK/$LINUX_ARCHIVE" "$LINUX_URL"
printf '%s  %s\n' "$LINUX_SHA256" "$WORK/$LINUX_ARCHIVE" | sha256sum -c -

tar -C "$WORK" -xf "$WORK/$LINUX_ARCHIVE"
test -d "$SRC"

# Temporary hardware diagnostic: mark the secondary MMU-off path directly via
# the physical PL011 so we can locate a stall before normal printk is usable.
python3 "$SMP_INSTRUMENT" "$SRC/arch/arm64/kernel/head.S"

grep -F 'hg680ka_uart_marker 0x41' "$SRC/arch/arm64/kernel/head.S"
grep -F 'hg680ka_uart_marker 0x42' "$SRC/arch/arm64/kernel/head.S"
grep -F 'hg680ka_uart_marker 0x43' "$SRC/arch/arm64/kernel/head.S"
grep -F 'hg680ka_uart_marker 0x50' "$SRC/arch/arm64/kernel/head.S"
grep -F 'hg680ka_uart_marker 0x44' "$SRC/arch/arm64/kernel/head.S"
grep -F 'hg680ka_uart_marker 0x45' "$SRC/arch/arm64/kernel/head.S"

# Do not build the enormous generic arm64 defconfig while debugging code that
# runs before secondary_start_kernel(). Start from tinyconfig and enable only
# the facilities required to reach the current SMP boundary. This also avoids
# compiling unrelated PCI/network/SoC/KVM drivers on every diagnostic turn.
printf 'Building Linux %s minimal ARM64 SMP diagnostic config...\n' "$LINUX_VERSION"
make -C "$SRC" O="$KOUT" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" tinyconfig

"$SRC/scripts/config" --file "$KOUT/.config" \
	-e SMP \
	--set-val NR_CPUS 4 \
	-e ARM_PSCI_FW \
	-e ARM_GIC \
	-e PRINTK \
	-e TTY \
	-e ARM_AMBA \
	-e SERIAL_AMBA_PL011 \
	-e SERIAL_AMBA_PL011_CONSOLE \
	-e ARM64_ERRATUM_843419 \
	-e ARM64_4K_PAGES \
	-d ARM64_VA_BITS_52 \
	-e ARM64_VA_BITS_48 \
	-d KVM \
	-d MODULES \
	-d PCI \
	-d ACPI \
	-d NET

make -C "$SRC" O="$KOUT" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" olddefconfig

# Fail early if Kconfig silently dropped any bring-up prerequisite.
grep -F 'CONFIG_SMP=y' "$KOUT/.config"
grep -F 'CONFIG_NR_CPUS=4' "$KOUT/.config"
grep -F 'CONFIG_ARM_PSCI_FW=y' "$KOUT/.config"
grep -F 'CONFIG_ARM_GIC=y' "$KOUT/.config"
grep -F 'CONFIG_PRINTK=y' "$KOUT/.config"
grep -F 'CONFIG_TTY=y' "$KOUT/.config"
grep -F 'CONFIG_ARM_AMBA=y' "$KOUT/.config"
grep -F 'CONFIG_SERIAL_CORE=y' "$KOUT/.config"
grep -F 'CONFIG_SERIAL_EARLYCON=y' "$KOUT/.config"
grep -F 'CONFIG_SERIAL_AMBA_PL011=y' "$KOUT/.config"
grep -F 'CONFIG_SERIAL_AMBA_PL011_CONSOLE=y' "$KOUT/.config"
grep -F 'CONFIG_ARM64_VA_BITS_48=y' "$KOUT/.config"
grep -F '# CONFIG_ARM64_VA_BITS_52 is not set' "$KOUT/.config"
grep -F 'CONFIG_ARM64_ERRATUM_843419=y' "$KOUT/.config"

JOBS="$(nproc)"
printf 'Compiling Image with make -j%s\n' "$JOBS"
make -C "$SRC" O="$KOUT" ARCH=arm64 CROSS_COMPILE="$CROSS_COMPILE" \
	-j"$JOBS" Image

IMAGE="$KOUT/arch/arm64/boot/Image"
VMLINUX="$KOUT/vmlinux"
test -s "$IMAGE"
test -s "$VMLINUX"

# Preserve the exact early-SMP machine code and symbol addresses in the small
# artifact. This lets us reason about B1 -> C1 -> P1 -> U1 without rebuilding
# just to recover a vmlinux disassembly.
{
	for sym in secondary_entry secondary_startup __cpu_setup __enable_mmu; do
		"${CROSS_COMPILE}nm" -n "$VMLINUX" | grep -E "[[:space:]][tT][[:space:]]${sym}$" || true
	done
} > "$ART/EARLY-SMP-SYMBOLS.txt"

{
	for sym in secondary_entry secondary_startup __cpu_setup __enable_mmu; do
		printf '\n===== %s =====\n' "$sym"
		"${CROSS_COMPILE}objdump" -d --disassemble="$sym" "$VMLINUX"
	done
} > "$ART/EARLY-SMP-DISASM.txt"

# Only the four-CPU image is useful now: maxcpus=1 has already proven that the
# boot CPU, timer, interrupt controller and init path work. Avoid duplicating
# every large payload in the diagnostic artifact.
DTB_SMP="$ART/hi3798mv310-hg680ka-smpdiag.dtb"
dtc -I dts -O dtb -o "$DTB_SMP" "$DTS"
test -s "$DTB_SMP"

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

# Keep TF-A diagnostics lock-free and minimally perturbing: report SMPEN and
# bracket the two GICv2 per-CPU setup calls, but do not modify cache state.
python3 "$ATF_SMP_INSTRUMENT" "$ATF_PM"
grep -F 'HG680-KA SMPEN diagnostic' "$ATF_PM"

# Reuse the hardware-proven vendor TF-A build path. This also asserts BL31 is
# linked at factory Fastboot's observed RVBAR address 0x08020000.
bash "$ROOT/scripts/hg680ka/build-arm64-atf-smoke.sh" "$ATF_OUT"
BL31="$ATF_OUT/artifacts/bl31.bin"
BL31_ELF="$ATF_OUT/artifacts/bl31.elf"
FIP_CREATE="$ATF_OUT/fip_create"
test -s "$BL31"
test -s "$BL31_ELF"
test -x "$FIP_CREATE"

BL33="$WORK/bl33-smpdiag.bin"
FIP="$ART/hg680ka-linux-${LINUX_VERSION}-smpdiag.fip"
DUMP="$ART/FIP-DUMP-smpdiag.txt"
cat "$UIMAGE" "$DTB_SMP" > "$BL33"
"$FIP_CREATE" --bl31 "$BL31" --bl33 "$BL33" "$FIP"
"$FIP_CREATE" --dump "$FIP" | tee "$DUMP"

cp "$IMAGE" "$ART/Image-6.18.46"
cp "$KOUT/.config" "$ART/linux-6.18.46.config"
cp "$BL31" "$ART/bl31.bin"
cp "$BL31_ELF" "$ART/bl31.elf"
cp "$DTS" "$ART/hg680ka-minimal.dts"
cp "$SMP_INSTRUMENT" "$ART/instrument-secondary.py"
cp "$ATF_SMP_INSTRUMENT" "$ART/instrument-atf-smpen.py"

: > "$ART/BUILD-INFO.txt"
printf 'Build host nproc:      %s\n' "$JOBS" | tee -a "$ART/BUILD-INFO.txt"
printf 'Linux raw Image size: %u bytes\n' "$image_size" | tee -a "$ART/BUILD-INFO.txt"
printf 'Linux padded size:    %u bytes\n' "$padded_size" | tee -a "$ART/BUILD-INFO.txt"
printf 'Kernel load address:  0x%08x\n' "$((KERNEL_LOAD_ADDR))" | tee -a "$ART/BUILD-INFO.txt"
printf 'SMP DTB size:         %u bytes\n' "$(stat -c %s "$DTB_SMP")" | tee -a "$ART/BUILD-INFO.txt"
printf 'SMP BL33 packed size: %u bytes\n' "$(stat -c %s "$BL33")" | tee -a "$ART/BUILD-INFO.txt"
printf 'Linux version:        %s\n' "$LINUX_VERSION" | tee -a "$ART/BUILD-INFO.txt"
printf 'Kernel source SHA256: %s\n' "$LINUX_SHA256" | tee -a "$ART/BUILD-INFO.txt"

(
	cd "$ART"
	sha256sum \
		Image-6.18.46 \
		Image-6.18.46.uImage \
		hi3798mv310-hg680ka-smpdiag.dtb \
		linux-6.18.46.config \
		bl31.bin \
		bl31.elf \
		hg680ka-linux-6.18.46-smpdiag.fip \
		> SHA256SUMS
	sha256sum -c SHA256SUMS
)

printf '\nHG680-KA Linux 6.18 minimal SMP diagnostic artifacts:\n'
ls -lh "$ART"
printf '\nBoard test (RAM/USB only):\n'
printf '  fatload usb 0:1 0x02000000 hg680ka-linux-%s-smpdiag.fip\n' "$LINUX_VERSION"
printf '  bootm 0x02000000\n'