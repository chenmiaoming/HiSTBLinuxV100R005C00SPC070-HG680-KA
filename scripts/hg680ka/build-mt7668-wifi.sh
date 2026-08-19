#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <kernel-output-dir> <artifact-output-dir>" >&2
    exit 2
}

[ "$#" -eq 2 ] || usage

KERNEL_OUT="$(realpath "$1")"
OUT_DIR="$(realpath -m "$2")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
KERNEL_SRC="$REPO_ROOT/source/kernel/linux-4.4.y"

# HiSilicon SPC060 still contains the MT7668BS vendor driver that was removed
# from the SPC070 tree. Pin the source so Phase B remains reproducible.
MT7668_SOURCE_REPO="https://github.com/07bug/HiSTBLinuxV100R005C00SPC060.git"
MT7668_SOURCE_COMMIT="a9f05973129d738e175416dd4a91b2c264ffcdd4"
MT7668_SOURCE_ROOT="${MT7668_SOURCE_ROOT:-$REPO_ROOT/.phase-b/HiSTBLinuxV100R005C00SPC060}"
MT7668_DRIVER_REL="source/component/wifi/drv/sdio_mt7668bs"

[ -d "$KERNEL_OUT" ] || {
    echo "Kernel output directory not found: $KERNEL_OUT" >&2
    exit 1
}
[ -f "$KERNEL_OUT/.config" ] || {
    echo "Kernel output is not configured: $KERNEL_OUT/.config" >&2
    exit 1
}
[ -f "$KERNEL_OUT/Module.symvers" ] || {
    echo "Kernel Module.symvers is missing; build the kernel first." >&2
    exit 1
}

grep -Fx 'CONFIG_MODULES=y' "$KERNEL_OUT/.config"
grep -Fx 'CONFIG_CFG80211=y' "$KERNEL_OUT/.config"
grep -Fx 'CONFIG_MMC=y' "$KERNEL_OUT/.config"

cd "$REPO_ROOT"
export SHELL=/bin/bash
source ./env.sh

command -v arm-histbv320-linux-gcc >/dev/null
command -v arm-histbv320-linux-strip >/dev/null

echo "MT7668 source: $MT7668_SOURCE_REPO"
echo "MT7668 source commit: $MT7668_SOURCE_COMMIT"
echo "Kernel output: $KERNEL_OUT"
echo "Toolchain: $(arm-histbv320-linux-gcc --version | head -n 1)"

rm -rf "$MT7668_SOURCE_ROOT"
mkdir -p "$(dirname "$MT7668_SOURCE_ROOT")"

# Partial clone avoids downloading the rest of the very large SPC060 SDK.
git clone \
    --filter=blob:none \
    --depth 1 \
    --branch master \
    --no-checkout \
    "$MT7668_SOURCE_REPO" \
    "$MT7668_SOURCE_ROOT"

git -C "$MT7668_SOURCE_ROOT" sparse-checkout init --cone
git -C "$MT7668_SOURCE_ROOT" sparse-checkout set "$MT7668_DRIVER_REL"
git -C "$MT7668_SOURCE_ROOT" checkout --detach "$MT7668_SOURCE_COMMIT"

test "$(git -C "$MT7668_SOURCE_ROOT" rev-parse HEAD)" = "$MT7668_SOURCE_COMMIT"

DRIVER_DIR="$MT7668_SOURCE_ROOT/$MT7668_DRIVER_REL"
MODULE="$DRIVER_DIR/wlan_mt7668_sdio.ko"

test -f "$DRIVER_DIR/Makefile"

# This is intentionally an out-of-tree build first.  The SPC060 source is from
# the same HiSTB SDK family and already has a Linux-4.4-oriented MT7668 SDIO
# Makefile.  Once hardware probe is proven, we can decide whether to vendor the
# driver into SPC070 or retain the pinned external-source build.
make \
    -C "$KERNEL_SRC" \
    O="$KERNEL_OUT" \
    ARCH=arm \
    CROSS_COMPILE=arm-histbv320-linux- \
    M="$DRIVER_DIR" \
    clean

make \
    -C "$KERNEL_SRC" \
    O="$KERNEL_OUT" \
    ARCH=arm \
    CROSS_COMPILE=arm-histbv320-linux- \
    M="$DRIVER_DIR" \
    -j"$(nproc)" \
    modules

test -f "$MODULE"

mkdir -p "$OUT_DIR"
cp "$MODULE" "$OUT_DIR/wlan_mt7668_sdio.ko"

cat > "$OUT_DIR/MT7668-SOURCE.txt" <<EOF
HG-680-KA Phase B MT7668 Wi-Fi driver source

Source repository: $MT7668_SOURCE_REPO
Source commit:     $MT7668_SOURCE_COMMIT
Source path:       $MT7668_DRIVER_REL
Kernel:            4.4.35-HG680-KA
Architecture:      ARMv7 / ARMHF
HIF:               SDIO
Expected SDIO ID:  037A:7608

Firmware is intentionally not redistributed by this build.  For hardware
bring-up use the HG-680-KA stock Android firmware extracted from its original
/system partition.
EOF

modinfo "$OUT_DIR/wlan_mt7668_sdio.ko" > "$OUT_DIR/wlan_mt7668_sdio.modinfo"
sha256sum \
    "$OUT_DIR/wlan_mt7668_sdio.ko" \
    "$OUT_DIR/MT7668-SOURCE.txt" \
    "$OUT_DIR/wlan_mt7668_sdio.modinfo" \
    > "$OUT_DIR/SHA256SUMS"

echo "Built Phase B artifacts:"
ls -lh "$OUT_DIR"
echo
cat "$OUT_DIR/wlan_mt7668_sdio.modinfo"
echo
cat "$OUT_DIR/SHA256SUMS"
