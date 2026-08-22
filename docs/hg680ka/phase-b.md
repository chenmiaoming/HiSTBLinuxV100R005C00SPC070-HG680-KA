# HG-680-KA Wi-Fi Phase B

Phase B brings up the onboard MediaTek MT7668 Wi-Fi function after Phase A made the SDIO bus deterministic.

## Hardware identity

The HG-680-KA enumerates the combo chip as two SDIO functions:

- `037A:7608` — MT7668 Wi-Fi function, handled by `wlan_mt7668_sdio.ko` in the stock Android image.
- `037A:7668` — MT7668 Bluetooth function, handled separately by `btmtk_sdio.ko`.

The stock Wi-Fi module is an ARMv7 module built for `3.18.24_hi3798mv310`, depends only on `cfg80211`, and contains the alias `sdio:c*v037Ad7608*`.

## Driver source choice

SPC070 no longer carries `source/component/wifi/drv/sdio_mt7668bs`, but the closely related HiSilicon SPC060 SDK still does. Its top-level Wi-Fi Makefile also has the original `CFG_HI_WIFI_DEVICE_MT7668BS` integration.

Phase B therefore uses the SPC060 driver pinned at:

- Repository: `https://github.com/07bug/HiSTBLinuxV100R005C00SPC060.git`
- Commit: `a9f05973129d738e175416dd4a91b2c264ffcdd4`
- Path: `source/component/wifi/drv/sdio_mt7668bs`

The driver is built out-of-tree against the HG-680-KA Linux 4.4.35 kernel. This keeps the port isolated from the main BSP while preserving a reproducible build path.

## Stock firmware package

The original HG-680-KA Android system contains the following MT7668 files used by the Wi-Fi/Bluetooth stack:

- `EEPROM_MT7668.bin`
- `EEPROM_MT7668_DMG.bin`
- `EEPROM_MT7668_e1.bin`
- `WIFI_RAM_CODE_MT7668.bin`
- `WIFI_RAM_CODE2_SDIO_MT7668.bin`
- `mt7668_patch_e1_hdr.bin`
- `mt7668_patch_e2_hdr.bin`
- `wifi.cfg`
- `woble_setting.bin`

The project now keeps this selected HG-680-KA factory payload under `firmware/hg680ka/mt7668/`. Unrelated Realtek firmware from the same factory archive is excluded. Exact SHA-256 values are recorded in `firmware/hg680ka/mt7668/SHA256SUMS`.

`scripts/hg680ka/install-mt7668-stock-firmware.sh` reconstructs the stored archive, verifies each file and installs it into a requested firmware directory. The system-image workflow uses this helper to populate `/lib/firmware` in the generated Ubuntu rootfs.

The stock `wifi.cfg` is retained rather than substituting a generic tuning file, because calibration and board power settings are device-specific. EEPROM/calibration files are consumed as firmware data only; this project does not write MT7668 eFuse/OTP.

## Hardware validation

Phase B was validated on the HG-680-KA with the Phase A SDIO configuration held at 3.3 V, 4-bit and 50 MHz.

Validated items:

- `wlan_mt7668_sdio.ko` loads against `4.4.35-HG680-KA`.
- SDIO function `037A:7608` binds to the WLAN driver.
- Stock firmware, EEPROM and `wifi.cfg` initialize successfully.
- `wlan0`, `p2p0` and `ap0` are registered.
- `wlan0` completes passive scan and reports real BSS/RSSI information.
- WPA2 association succeeds on 2.4 GHz.
- DHCP and bidirectional IP traffic succeed on 2.4 GHz.
- WPA2 association succeeds on 5 GHz.
- 5 GHz VHT80 2x2 operation reaches a reported PHY rate of 866.5 Mbit/s.
- DHCP and gateway traffic succeed on the 5 GHz link with no observed loss in the validation sample.
- `/proc/net/wlan/get_txpwr_tbl` follows the active channel and returns board-calibrated target powers rather than the unconstrained `31.5 dBm` regulatory-table placeholder.

For the 2.4 GHz validation on channel 6, target power was typically 18 dBm for DSSS and 16 dBm for OFDM/HT, with the driver's CDD path 3 dB lower. On the 5 GHz VHT80 validation link, board/target limits varied by modulation and MCS as expected, including reduced target power at high VHT MCS rates.

## TxPwrLimit note

The driver attempts to load `TxPwrLimit_MT76x8.dat`, and the Linux firmware loader reports `-ENOENT` when it is absent. The original HG-680-KA Android `/system` and `/data` partitions do not contain this file, and the stock Android WLAN module contains the same filename/path lookup strings.

The runtime power query shows that the missing external table leaves the regulatory-limit column at the driver's `31.5 dBm` maximum representation, but the actual target power remains constrained by the board/firmware calibration table. Phase B therefore does not invent or bundle a replacement `TxPwrLimit_MT76x8.dat`.

## Known limitations / deferred work

- Regulatory domain currently reports `country 00: DFS-UNSET`; AP-mode regulatory handling remains to be validated before treating AP mode as production-ready.
- `iw phy` reports `0.0 dBm` channel maximums even though the firmware power table reports non-zero calibrated target power. This appears to be a cfg80211 reporting limitation of the vendor driver rather than zero RF output.
- AP/hostapd and P2P modes have not yet been validated.
- Sustained throughput/iperf and long-duration stress testing are not Phase B merge blockers, but remain useful characterization work.
- The Phase A workaround intentionally disables 1.8 V/UHS and keeps SDIO at 3.3 V / 4-bit / 50 MHz. Re-enabling 1.8 V/UHS is deferred to a separate performance-focused phase after functional Wi-Fi and Bluetooth support are stable.

## Phase B completion criteria

Phase B is considered complete when the MT7668 WLAN function can be reproducibly built, loaded and used as a STA on both 2.4 GHz and 5 GHz with WPA2, DHCP and real IP traffic. Those criteria have been met on hardware.
