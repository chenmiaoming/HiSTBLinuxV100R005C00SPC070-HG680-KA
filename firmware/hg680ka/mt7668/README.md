# HG-680-KA stock MT7668 firmware

This directory contains the MT7668 firmware/calibration payload selected from the original FiberHome HG-680-KA factory firmware archive used during board bring-up.

Only files relevant to the on-board MediaTek MT7668 SDIO combo device are retained. Realtek `rtl8723*`, `rtl8761*`, and `rtl8822*` payloads from the same factory archive are deliberately excluded because the HG-680-KA hardware validated by this project enumerates MediaTek SDIO functions `037A:7608` (Wi-Fi) and `037A:7668` (Bluetooth).

## Selected files

| File | Size | SHA-256 | Role |
| --- | ---: | --- | --- |
| `EEPROM_MT7668.bin` | 1024 | `a50c8c95ff37eb3e1d69f26f9b7ccd1c34d95b83ddc89abb835d1157484a4042` | MT7668 EEPROM/calibration image used by the vendor stack |
| `EEPROM_MT7668_DMG.bin` | 1024 | `afa07c6b183557ea3dfbbd0fa328d9c828444b4723c3f912a73cfca8e6cadbb2` | alternate factory EEPROM image |
| `EEPROM_MT7668_e1.bin` | 1024 | `a042c6ceb77ae4a0c367e5e5522cbf21f767936b8799a781096e1e72684d957c` | E1-revision EEPROM image |
| `WIFI_RAM_CODE_MT7668.bin` | 462904 | `4c2e31238bcc051f105752f36f9fd57fc5aa068b6b1c394961372ee97cb58fa5` | Wi-Fi firmware RAM code |
| `WIFI_RAM_CODE2_SDIO_MT7668.bin` | 51816 | `35faff6a613fefcbe33a6f6d8df885be76c546f9e78ba8ab93056a816ad87254` | SDIO-specific Wi-Fi RAM code |
| `mt7668_patch_e1_hdr.bin` | 152302 | `519083ebb8318d9cfc8eaaaa7470d1a266c8f32275df3c62e3619d6c07f97389` | Bluetooth ROM patch for E1 |
| `mt7668_patch_e2_hdr.bin` | 174046 | `8a6591d85255a04dcdcddfa79e9d2a0fa9a961016ac3ca6b3dfb3fe716a20330` | Bluetooth ROM patch for E2 |
| `wifi.cfg` | 846 | `1d48bb445da63a27e47db1af3daf1f32c1967354be8b394e8220beac041e20b3` | board/vendor Wi-Fi configuration |
| `woble_setting.bin` | 1011 | `ac2a4fee28e06593cc84997dc550256cbf5eb549d160377812abc4f1dc2ab052` | Bluetooth WoBLE settings |

`SHA256SUMS` is authoritative for byte-for-byte verification.

## Repository representation

To keep the factory payload auditable while avoiding a collection of opaque loose blobs, the selected files are packed into one `tar.xz` stream and that stream is stored as ordered Base64 parts under `archive/`.

`scripts/hg680ka/install-mt7668-stock-firmware.sh` reconstructs the archive, verifies that it can be decoded/extracted, checks every selected file against `SHA256SUMS`, and only then installs the files into the requested firmware directory.

Example:

```sh
scripts/hg680ka/install-mt7668-stock-firmware.sh /tmp/hg680ka-firmware
```

The system-image workflow uses a staging directory and then copies the verified files into `/lib/firmware` in the generated Ubuntu root filesystem.

## Provenance and scope

These files were extracted from an original HG-680-KA factory firmware package supplied for this board. They are preserved as hardware-support artifacts; no claim is made here about a general redistribution licence or suitability for unrelated MT7668 products.

In particular, EEPROM/calibration data is board/vendor specific. Do not write these files to MT7668 eFuse/OTP, and do not substitute calibration data from another board. The Linux drivers consume them as firmware/configuration files only.
