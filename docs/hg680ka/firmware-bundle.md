# HG-680-KA MT7668 firmware bundle integration

This change makes the generated development image self-contained for the board's MT7668 Wi-Fi/Bluetooth firmware path.

The factory firmware archive was filtered by hardware identity rather than copied wholesale. The HG-680-KA used by this project enumerates `037A:7608` (Wi-Fi) and `037A:7668` (Bluetooth), therefore the selected bundle contains the MT7668 EEPROM, RAM code, Bluetooth patches, `wifi.cfg`, and WoBLE settings. Realtek firmware sets found in the same factory image are excluded.

The selected payload is stored as a split Base64 representation of a compressed archive. This is an implementation detail of the repository representation; consumers should use `scripts/hg680ka/install-mt7668-stock-firmware.sh` rather than handling the parts directly.

The installer is fail-closed:

1. concatenate the ordered archive parts;
2. Base64-decode the archive;
3. run `xz -t` before extraction;
4. require the exact expected top-level file set;
5. verify every file with `firmware/hg680ka/mt7668/SHA256SUMS`;
6. install only the verified files;
7. verify the installed copy again.

A short GitHub Actions job runs the same reconstruction path before the longer kernel/rootfs build, so accidental corruption of any archive part is detected early.
