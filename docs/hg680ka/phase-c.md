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
- stock init logic identifies `037A:7668` as `MT7668BS` and loads `btmtk_sdio.ko`

Do not load the stock 3.18 module into the 4.4.35 kernel.

## Driver source selected for Phase C

Google Coral published MediaTek's GPLv2 MT7668 Bluetooth-over-SDIO driver at:

`https://coral.googlesource.com/mt7668-bluetooth-mod`

Phase C pins commit:

`0b3cfd4b7d7a39ee33b590a5d380f63924a93940`

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
2. Copy only the required stock firmware into `/lib/firmware` on the temporary USB Linux rootfs.
3. Load the Phase C module.
4. Verify function 2 binds to the MediaTek Bluetooth SDIO driver.
5. Verify firmware/ROM patch download succeeds.
6. Verify `hci0` appears.
7. Read controller information with BlueZ tools.
8. Test BR/EDR inquiry.
9. Test BLE scan.
10. Exercise unload/reload and repeated scans before considering persistent integration.

## Safety

Phase C does not require writes to eMMC boot areas, RPMB, OTP/eFuse, or bootloader environment.

The original Android partitions should remain mounted read-only during archaeology. Do not use factory/test commands that write MT7668 eFuse or board calibration data.
