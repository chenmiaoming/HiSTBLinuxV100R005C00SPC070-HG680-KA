# HG-680-KA Phase C: MT7668 Bluetooth over SDIO

## Scope

Phase C brings up the Bluetooth function of the on-board MediaTek MT7668 combo device while preserving the already validated Wi-Fi path.

The board exposes one SDIO card with two functions:

- function 1: `037A:7608` -- Wi-Fi, already handled by Phase B
- function 2: `037A:7668` -- Bluetooth

The current HiSTBLinux 4.4 kernel enumerates function 2 but leaves it unbound.

## Stock Android evidence

Read-only inspection of the HG-680-KA stock Android system found:

- module: `/system/lib/modules/btmtk_sdio.ko`
- description: `Mediatek Bluetooth driver ver v0.0.0.52_2018070501_cstm0504`
- kernel vermagic: `3.18.24_hi3798mv310 SMP mod_unload ARMv7 p2v8`
- SDIO aliases include `sdio:c*v037Ad7668*`
- stock source path embedded in the module points at `device/hisilicon/bigfish/bluetooth/mt7668bs/driver/`
- firmware files include `mt7668_patch_e1_hdr.bin` and `mt7668_patch_e2_hdr.bin`
- the same stock firmware directory also contains `EEPROM_MT7668.bin`
- stock `wifi.cfg` contains `EfuseBufferModeCal 0`; Phase C records this value but does not assume its semantics without matching source
- stock init logic identifies `037A:7668` as `MT7668BS`

The stock firmware files observed on this board are:

| File | Size | SHA-256 |
| --- | ---: | --- |
| `mt7668_patch_e1_hdr.bin` | about 149 KiB | `519083ebb8318d9cfc8eaaaa7470d1a266c8f32275df3c62e3619d6c07f97389` |
| `mt7668_patch_e2_hdr.bin` | about 170 KiB | `8a6591d85255a04dcdcddfa79e9d2a0fa9a961016ac3ca6b3dfb3fe716a20330` |
| `EEPROM_MT7668.bin` | 1024 bytes | `a50c8c95ff37eb3e1d69f26f9b7ccd1c34d95b83ddc89abb835d1157484a4042` |
| `wifi.cfg` | 846 bytes | `1d48bb445da63a27e47db1af3daf1f32c1967354be8b394e8220beac041e20b3` |

### Stock MT7668 initialization sequence

`/system/etc/init.bt.sh` first loads the board SDIO-detect module, waits for SDIO enumeration, inspects each SDIO `uevent`, and selects a Bluetooth driver by SDIO ID.

For `037A:7668` the MT7668-specific branch is simply:

```text
hi_sdio_detect.ko
        |
        v
wait for 037A:7668
        |
        v
btmtk_sdio.ko
```

Unlike the RTL8822BS and QCA6174 branches in the same script, the MT7668 branch does **not** load `hi_rfkill.ko` or `rfkill-hisi-bt.ko` before loading `btmtk_sdio.ko`.

`/system/bin/opt/etc/init.stb.sh` also contains a legacy/fallback path which loads several rfkill modules unconditionally. That fallback is not evidence that the normal MT7668-specific path requires them; the device-ID-driven `init.bt.sh` path above is the better reference for Phase C bring-up.

Do not load the stock 3.18 module into the 4.4.35 kernel.

## Driver source selected for Phase C

Google Coral published MediaTek's GPLv2 MT7668 Bluetooth-over-SDIO driver at:

`https://coral.googlesource.com/mt7668-bluetooth-mod`

Phase C pins commit:

`040ca262f203faec9f1337db5b1b991cfba72ecf`

This is deliberately the revision immediately before Coral commit `dbf041d` (`Set hci_dev's hw_info field`). The later commit assigns `hdev->hw_info`, while the HG-680-KA vendor Linux 4.4.35 `struct hci_dev` has no `hw_info` member. The pinned revision already contains Coral's explicit Linux 4.4 compatibility changes and HCI-device registration support, so it avoids carrying a source edit solely to undo that newer-kernel-only field assignment.

This source family is a strong match for the HG-680-KA stock binary:

- MediaTek Bluetooth-over-SDIO implementation
- vendor ID `0x037A`
- device ID `0x7668`
- SDIO function number 2
- firmware names `mt7668_patch_e1_hdr.bin` and `mt7668_patch_e2_hdr.bin`
- EEPROM configuration support using `EEPROM_MT7668.bin`

The published history also contains explicit Linux 4.4 compatibility work and HCI-device registration support, so Phase C starts with an out-of-tree build against the HG-680-KA 4.4.35 kernel rather than trying to insert the stock Android 3.18 binary.

## Current target-kernel state

The HG-680-KA kernel already has the Bluetooth core built in, including BR/EDR and LE support. Runtime boot logs show the Bluetooth core and the generic Bluetooth SDIO driver initializing before the MT7668 card enumerates.

Relevant confirmed kernel options include:

```text
CONFIG_BT=y
CONFIG_BT_BREDR=y
CONFIG_BT_LE=y
CONFIG_BT_HCIBTSDIO=y
CONFIG_RFKILL=y
CONFIG_PM=y
CONFIG_PM_SLEEP=y
```

The generic `btsdio` driver does not bind `mmc2:0001:2`; the MediaTek-specific function therefore remains available for the Phase C driver.

## Firmware policy

Proprietary board firmware is not committed to this public repository or uploaded by CI.

For hardware testing, extract the firmware from the board's original Android `/system/etc/firmware` partition and place the required files in the Linux firmware search path. At minimum the driver is expected to request one of:

- `mt7668_patch_e1_hdr.bin`
- `mt7668_patch_e2_hdr.bin`

The source can also consume `EEPROM_MT7668.bin` depending on its EEPROM-access configuration. Preserve the board's original EEPROM data; never replace it with firmware from another board.

## Build

After building the HG-680-KA kernel, run:

```sh
scripts/hg680ka/build-mt7668-bluetooth.sh \
    <kernel-output-dir> \
    <artifact-output-dir>
```

CI workflow:

`.github/workflows/build-mt7668-phase-c.yml`

Expected artifact:

`btmtksdio.ko`

Required metadata checks include:

- ARM ELF module
- `4.4.35-HG680-KA` vermagic
- SDIO alias `sdio:c*v037Ad7668*`

## Hardware validation order

1. Verify `mmc2:0001:2` is still `037A:7668` and unbound.
2. Ensure `hi_sdio_detect` has already powered/enumerated the combo device; no additional rfkill module is assumed for the MT7668-specific path.
3. Copy only the required stock firmware into `/lib/firmware` on the temporary USB Linux rootfs.
4. Load the Phase C module.
5. Verify function 2 binds to the MediaTek Bluetooth SDIO driver.
6. Verify firmware/ROM patch download succeeds.
7. Verify `hci0` appears.
8. Read controller information with BlueZ tools.
9. Test BR/EDR inquiry.
10. Test BLE scan.
11. Exercise unload/reload and repeated scans before considering persistent integration.

## Safety

Phase C does not require writes to eMMC boot areas, RPMB, OTP/eFuse, or bootloader environment.

The original Android partitions should remain mounted read-only during archaeology. Do not use factory/test commands that write MT7668 eFuse or board calibration data.
