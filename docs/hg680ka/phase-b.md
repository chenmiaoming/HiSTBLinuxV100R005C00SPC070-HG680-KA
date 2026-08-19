# HG-680-KA Wi-Fi Phase B

Phase B brings up the onboard MediaTek MT7668 Wi-Fi function after Phase A made the SDIO bus deterministic.

## Hardware identity

The HG-680-KA enumerates the combo chip as two SDIO functions:

- `037A:7608` — MT7668 Wi-Fi function, handled by `wlan_mt7668_sdio.ko` in the stock Android image.
- `037A:7668` — MT7668 Bluetooth function, handled separately by `btmtk_sdio.ko`.

The stock Wi-Fi module is an ARMv7 module built for `3.18.24_hi3798mv310`, depends only on `cfg80211`, and contains the alias `sdio:c*v037Ad7608*`.

## Driver source choice

SPC070 no longer carries `source/component/wifi/drv/sdio_mt7668bs`, but the closely related HiSilicon SPC060 SDK still does.  Its top-level Wi-Fi Makefile also has the original `CFG_HI_WIFI_DEVICE_MT7668BS` integration.

Phase B therefore starts from the SPC060 driver pinned at:

- Repository: `https://github.com/07bug/HiSTBLinuxV100R005C00SPC060.git`
- Commit: `a9f05973129d738e175416dd4a91b2c264ffcdd4`
- Path: `source/component/wifi/drv/sdio_mt7668bs`

The first milestone deliberately builds that source out-of-tree against the HG-680-KA Linux 4.4.35 kernel.  This keeps the first experiment small and lets CI expose any API/ABI differences before the source is permanently integrated into SPC070.

## Stock firmware policy

The original HG-680-KA Android system contains the following MT7668 files:

- `EEPROM_MT7668.bin`
- `EEPROM_MT7668_DMG.bin`
- `EEPROM_MT7668_e1.bin`
- `WIFI_RAM_CODE_MT7668.bin`
- `WIFI_RAM_CODE2_SDIO_MT7668.bin`
- `mt7668_patch_e1_hdr.bin`
- `mt7668_patch_e2_hdr.bin`
- `wifi.cfg`

These binaries are not committed or redistributed by Phase B.  Initial hardware tests should use the board's own stock files extracted read-only from the original Android `/system` partition.

The stock `wifi.cfg` is also retained for first bring-up rather than substituting the newer CoreELEC tuning file, because calibration/power settings differ.

## Milestones

1. Build `wlan_mt7668_sdio.ko` for `4.4.35-HG680-KA` in CI.
2. Load the stock firmware/config and bind `037A:7608` to the module.
3. Create `wlan0` and complete `iw` scan.
4. Associate with an AP and validate DHCP/ping.
5. Validate AP mode/hostapd and throughput.
6. Revisit 1.8 V/UHS only after the 3.3 V / 4-bit / 50 MHz path is functionally stable.
