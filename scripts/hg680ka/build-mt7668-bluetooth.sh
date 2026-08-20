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

# Google Coral published MediaTek's GPLv2 MT7668 Bluetooth-over-SDIO driver.
# Pin the last revision before dbf041d ("Set hci_dev's hw_info field").
# That later change assigns hdev->hw_info, but the HG-680-KA vendor Linux 4.4
# struct hci_dev has no such member.  This revision already contains Coral's
# explicit Linux 4.4 compatibility work and HCI-device registration support.
BT_SOURCE_REPO="https://coral.googlesource.com/mt7668-bluetooth-mod"
BT_SOURCE_COMMIT="040ca262f203faec9f1337db5b1b991cfba72ecf"
BT_SOURCE_ROOT="${BT_SOURCE_ROOT:-$REPO_ROOT/.phase-c/mt7668-bluetooth-mod}"

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
grep -Fx 'CONFIG_MMC=y' "$KERNEL_OUT/.config"
grep -Fx 'CONFIG_BT=y' "$KERNEL_OUT/.config"
grep -Fx 'CONFIG_PM=y' "$KERNEL_OUT/.config"

cd "$REPO_ROOT"
export SHELL=/bin/bash
source ./env.sh

command -v arm-histbv320-linux-gcc >/dev/null
command -v arm-histbv320-linux-strip >/dev/null

echo "MT7668 Bluetooth source: $BT_SOURCE_REPO"
echo "MT7668 Bluetooth source commit: $BT_SOURCE_COMMIT"
echo "Kernel output: $KERNEL_OUT"
echo "Toolchain: $(arm-histbv320-linux-gcc --version | head -n 1)"

rm -rf "$BT_SOURCE_ROOT"
mkdir -p "$BT_SOURCE_ROOT"

git -C "$BT_SOURCE_ROOT" init -q
git -C "$BT_SOURCE_ROOT" remote add origin "$BT_SOURCE_REPO"
git -C "$BT_SOURCE_ROOT" fetch --depth 1 origin "$BT_SOURCE_COMMIT"
git -C "$BT_SOURCE_ROOT" checkout --detach FETCH_HEAD

test "$(git -C "$BT_SOURCE_ROOT" rev-parse HEAD)" = "$BT_SOURCE_COMMIT"
test -f "$BT_SOURCE_ROOT/Makefile"
test -f "$BT_SOURCE_ROOT/btmtk_sdio.c"
test -f "$BT_SOURCE_ROOT/btmtk_main.c"

# Build the driver directly through the target kernel's Kbuild tree.  This
# avoids the external project's host-kernel default KERNEL_SRC setting while
# preserving its obj-m / btmtksdio-objs definitions.
make \
    -C "$KERNEL_SRC" \
    O="$KERNEL_OUT" \
    ARCH=arm \
    CROSS_COMPILE=arm-histbv320-linux- \
    M="$BT_SOURCE_ROOT" \
    clean

make \
    -C "$KERNEL_SRC" \
    O="$KERNEL_OUT" \
    ARCH=arm \
    CROSS_COMPILE=arm-histbv320-linux- \
    M="$BT_SOURCE_ROOT" \
    -j"$(nproc)" \
    modules

MODULE="$BT_SOURCE_ROOT/btmtksdio.ko"
test -f "$MODULE"

mkdir -p "$OUT_DIR"
cp "$MODULE" "$OUT_DIR/btmtksdio.ko"

cat > "$OUT_DIR/MT7668-BLUETOOTH-SOURCE.txt" <<EOF
HG-680-KA Phase C MT7668 Bluetooth-over-SDIO driver source

Source repository: $BT_SOURCE_REPO
Source commit:     $BT_SOURCE_COMMIT
Kernel:            4.4.35-HG680-KA
Architecture:      ARMv7 / ARMHF
HIF:               SDIO function 2
Expected SDIO ID:  037A:7668

HG-680-KA stock Android evidence:
- stock module: btmtk_sdio.ko
- stock module version: v0.0.0.52_2018070501_cstm0504
- stock modalias includes sdio:c*v037Ad7668*
- stock firmware contains mt7668_patch_e1_hdr.bin and mt7668_patch_e2_hdr.bin

Firmware is intentionally not redistributed by this build.  For hardware
bring-up, copy the required files from the HG-680-KA stock Android /system
partition into the Linux firmware search path.
EOF

modinfo "$OUT_DIR/btmtksdio.ko" > "$OUT_DIR/btmtksdio.modinfo"
sha256sum \
    "$OUT_DIR/btmtksdio.ko" \
    "$OUT_DIR/MT7668-BLUETOOTH-SOURCE.txt" \
    "$OUT_DIR/btmtksdio.modinfo" \
    > "$OUT_DIR/SHA256SUMS"

echo "Built Phase C artifacts:"
ls -lh "$OUT_DIR"
echo
cat "$OUT_DIR/btmtksdio.modinfo"
echo
cat "$OUT_DIR/SHA256SUMS"
