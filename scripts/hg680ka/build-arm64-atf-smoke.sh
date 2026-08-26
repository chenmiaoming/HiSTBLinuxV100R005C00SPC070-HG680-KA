#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/out/hg680ka-arm64-smoke}"
ATF="$ROOT/source/kernel/arm-trusted-firmware"
SMOKE="$ROOT/tools/hg680ka/arm64-smoke"
TOOLCHAIN_BIN="$ROOT/tools/linux/toolchains/aarch64-histbv100-linux/bin"
CROSS_COMPILE="$TOOLCHAIN_BIN/aarch64-gcc51_glibc222-linux-gnu-"
FACTORY_BL31_BASE=0x08020000

rm -rf "$OUT"
mkdir -p "$OUT/artifacts"

for tool in gcc ld objcopy; do
        if [[ ! -x "${CROSS_COMPILE}${tool}" ]]; then
                echo "missing vendor AArch64 tool: ${CROSS_COMPILE}${tool}" >&2
                exit 1
        fi
done
for tool in dtc mkimage gcc readelf; do
        command -v "$tool" >/dev/null || {
                echo "missing host tool: $tool" >&2
                exit 1
        }
done

"${CROSS_COMPILE}gcc" --version | head -n 1

SMOKE_OUT="$OUT/smoke"
make -C "$SMOKE" \
        CROSS_COMPILE="$CROSS_COMPILE" \
        OUT="$SMOKE_OUT" \
        -j"$(nproc)"

# Build only BL31. The factory Fastboot remains responsible for DDR and image
# loading; BL1/BL2 are intentionally outside this non-destructive bring-up path.
#
# Keep DISABLE_TEE=0 even though no BL32/SPD is used. In this vendor TF-A tree
# DISABLE_TEE=1 deliberately turns BL33 into Secure-world EL1 and skips the
# normal GIC secure setup. For a conventional ARM64 Linux path BL33 must remain
# non-secure, so use the normal-world path with SPD=none.
ATF_OUT="$OUT/atf"
make -C "$ATF" \
        PLAT=hi3798mv310 \
        CROSS_COMPILE="$CROSS_COMPILE" \
        O="$ATF_OUT" \
        SPD=none \
        DISABLE_TEE=0 \
        DEBUG=1 \
        bl31 \
        -j"$(nproc)"

BL31_DIR="$ATF_OUT/build/hi3798mv310/debug/bl31"
BL31="$ATF_OUT/build/hi3798mv310/debug/bl31.bin"
BL31_ELF="$BL31_DIR/bl31.elf"
test -s "$BL31"
test -s "$BL31_ELF"

# The installed HG680-KA Fastboot has now been observed on hardware to copy
# BL31 to 0x08020000 and program that value into RVBAR. This old TF-A image is
# not position independent, so reject any build whose ELF entry point differs.
bl31_entry=$(readelf -h "$BL31_ELF" | awk '/Entry point address:/ { print $4 }')
test -n "$bl31_entry"
if (( bl31_entry != FACTORY_BL31_BASE )); then
        printf 'BL31 entry mismatch: built=%s factory=0x%08x\n' \
                "$bl31_entry" "$FACTORY_BL31_BASE" >&2
        exit 1
fi
printf 'BL31 entry matches factory Fastboot RVBAR: 0x%08x\n' "$FACTORY_BL31_BASE"

# The checked-in vendor fip_create binary is a legacy 32-bit host executable.
# Rebuild the same source natively so CI and modern development hosts do not
# require an i386 runtime.
FIP_SRC="$ATF/tools/fip_create"
FIP_CREATE="$OUT/fip_create"
gcc -Wall -Werror -pedantic -std=c99 -O2 \
        -I"$FIP_SRC" \
        "$FIP_SRC/fip_create.c" \
        -o "$FIP_CREATE"

FIP="$OUT/artifacts/hg680ka-arm64-smoke.fip"
"$FIP_CREATE" \
        --bl31 "$BL31" \
        --bl33 "$SMOKE_OUT/bl33.bin" \
        "$FIP"

"$FIP_CREATE" --dump "$FIP" | tee "$OUT/artifacts/FIP-DUMP.txt"

cp "$BL31" "$OUT/artifacts/bl31.bin"
cp "$BL31_ELF" "$OUT/artifacts/bl31.elf"
cp "$SMOKE_OUT/smoke.elf" "$OUT/artifacts/bl33-smoke.elf"
cp "$SMOKE_OUT/smoke.bin" "$OUT/artifacts/bl33-smoke.bin"
cp "$SMOKE_OUT/smoke.uImage" "$OUT/artifacts/bl33-smoke.uImage"
cp "$SMOKE_OUT/smoke.dtb" "$OUT/artifacts/bl33-smoke.dtb"
cp "$SMOKE_OUT/bl33.bin" "$OUT/artifacts/bl33.bin"

(
        cd "$OUT/artifacts"
        sha256sum \
                bl31.bin \
                bl31.elf \
                bl33-smoke.elf \
                bl33-smoke.bin \
                bl33-smoke.uImage \
                bl33-smoke.dtb \
                bl33.bin \
                hg680ka-arm64-smoke.fip \
                > SHA256SUMS
)

printf '\nARM64 handoff artifacts:\n'
ls -lh "$OUT/artifacts"
printf '\n'
cat "$OUT/artifacts/SHA256SUMS"
