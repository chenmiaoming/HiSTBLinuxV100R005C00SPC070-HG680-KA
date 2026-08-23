#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <firmware-output-dir>" >&2
    exit 2
}

[ "$#" -eq 1 ] || usage

OUT_DIR="$(realpath -m "$1")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FW_DIR="$REPO_ROOT/firmware/hg680ka/mt7668"
ARCHIVE_DIR="$FW_DIR/archive"
RAW_ARCHIVE="$ARCHIVE_DIR/mt7668-stock-firmware.tar.xz"
SUMS="$FW_DIR/SHA256SUMS"

EXPECTED_ARCHIVE_SIZE=595036
EXPECTED_ARCHIVE_SHA256="36c59eab1c2bf37ad99bf8205fba45d15835858fb84e568c3c4a4344564e67f8"

EXPECTED_FILES=(
    EEPROM_MT7668.bin
    EEPROM_MT7668_DMG.bin
    EEPROM_MT7668_e1.bin
    WIFI_RAM_CODE2_SDIO_MT7668.bin
    WIFI_RAM_CODE_MT7668.bin
    mt7668_patch_e1_hdr.bin
    mt7668_patch_e2_hdr.bin
    wifi.cfg
    woble_setting.bin
)

command -v tar >/dev/null
command -v xz >/dev/null
command -v sha256sum >/dev/null
command -v install >/dev/null
command -v stat >/dev/null

test -f "$SUMS"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ARCHIVE="$TMP/mt7668-stock-firmware.tar.xz"
EXTRACT="$TMP/extract"
mkdir -p "$EXTRACT"

if [ -f "$RAW_ARCHIVE" ]; then
    # Preferred representation: keep the small (~581 KiB) verified archive directly
    # in Git. This avoids fragile Base64 reconstruction and does not require Git LFS.
    cp "$RAW_ARCHIVE" "$ARCHIVE"
else
    # Compatibility path for the older split-Base64 representation. This can be
    # removed after the raw archive has landed and the old parts are deleted.
    shopt -s nullglob
    PARTS=("$ARCHIVE_DIR"/mt7668-stock-firmware.tar.xz.b64.part*)
    shopt -u nullglob

    [ "${#PARTS[@]}" -gt 0 ] || {
        echo "Missing MT7668 archive: $RAW_ARCHIVE" >&2
        echo "No legacy Base64 archive parts found in $ARCHIVE_DIR either" >&2
        exit 1
    }

    command -v base64 >/dev/null
    # Parts are zero-padded and shell glob order is therefore archive order.
    cat "${PARTS[@]}" | base64 --decode > "$ARCHIVE"
fi

ACTUAL_ARCHIVE_SIZE="$(stat -c %s "$ARCHIVE")"
if [ "$ACTUAL_ARCHIVE_SIZE" -ne "$EXPECTED_ARCHIVE_SIZE" ]; then
    echo "MT7668 archive size mismatch: expected $EXPECTED_ARCHIVE_SIZE bytes, got $ACTUAL_ARCHIVE_SIZE" >&2
    exit 1
fi

printf '%s  %s\n' "$EXPECTED_ARCHIVE_SHA256" "$ARCHIVE" | sha256sum -c -

# Validate both compression and tar structure before extracting anything.
xz -t "$ARCHIVE"
tar -tJf "$ARCHIVE" >/dev/null

tar -xJf "$ARCHIVE" -C "$EXTRACT"

# Reject path surprises and unexpected regular files before installing anything.
for path in "${EXPECTED_FILES[@]}"; do
    test -f "$EXTRACT/$path" || {
        echo "Missing expected firmware file: $path" >&2
        exit 1
    }
done

mapfile -t ACTUAL_FILES < <(
    find "$EXTRACT" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort
)
mapfile -t EXPECTED_SORTED < <(printf '%s\n' "${EXPECTED_FILES[@]}" | LC_ALL=C sort)

if [ "${ACTUAL_FILES[*]}" != "${EXPECTED_SORTED[*]}" ]; then
    echo "Unexpected file set in MT7668 stock archive:" >&2
    printf '  %s\n' "${ACTUAL_FILES[@]}" >&2
    exit 1
fi

(
    cd "$EXTRACT"
    sha256sum -c "$SUMS"
)

mkdir -p "$OUT_DIR"
for path in "${EXPECTED_FILES[@]}"; do
    install -m 0644 "$EXTRACT/$path" "$OUT_DIR/$path"
done

# Verify the installed copy as well.
(
    cd "$OUT_DIR"
    sha256sum -c "$SUMS"
)

echo "Installed verified HG-680-KA MT7668 firmware to: $OUT_DIR"
ls -lh "$OUT_DIR"
