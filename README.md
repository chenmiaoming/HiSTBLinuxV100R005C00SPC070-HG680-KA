# HiSTBLinux SPC070 for FiberHome HG-680-KA

This repository is a board-focused adaptation of the HiSilicon HiSTBLinux V100R005C00SPC070 SDK for the **FiberHome HG-680-KA** set-top box. The current goal is to turn the board into a reproducible general-purpose Linux development/server platform while retaining the vendor Linux 4.4 multimedia stack as a reference for hardware enablement.

The current deployed path is **vendor Linux 4.4.35 + ARMHF + Ubuntu 22.04 rootfs**, with **both the adapted kernel and root filesystem installed on internal eMMC**. The board now boots standalone using the existing HiSilicon Fastboot loader with modified boot environment/arguments. Earlier non-destructive USB boot remains available as a development and recovery workflow, not the primary deployment. As of October 2026, the eMMC system has been serving DNS caching and filtering on a private office network for approximately two weeks (operator-reported). A separate long-term effort is planned for **mainline/stable Linux 6.18.y on ARM64**.

> This is not a generic SPC070 reference-board configuration. Use the `HG-680-KA` board profile for this hardware.

## HG-680-KA hardware fingerprint

The table below describes the physical unit used for development and validation in this repository. HG-680-KA units from another operator, production batch, or PCB revision should be compared against these details before assuming that the same DTS, DDR setup, eMMC layout, or wireless wiring applies.

| Item | Observed on the reference HG-680-KA | Status / alignment note |
| --- | --- | --- |
| Manufacturer / model | FiberHome / 烽火 `HG680-KA` | primary target board |
| Stock Android product model | `HG680-KA` | observed in stock Android properties |
| Stock Android hardware ID | `HG680-AYRRT-0B` | useful for comparing operator/board variants |
| SoC package marking | HiSilicon `Hi3798MRBCV311` | handled by the Hi3798MV310-family BSP |
| CPU | 4 × ARM Cortex-A53 | vendor BSP currently boots these CPUs through the 32-bit ARM/ARMHF path |
| RAM | 1 GiB DDR3 | working |
| Stock DDR configuration | `hi3798m31dmd_hi3798mv310_DDR3-1866_1GB_16bitx2_4layers.reg` | this differs from the SPC070 MV310 reference-board DDR topology; do not replace the stock DDR/Fastboot image with the generic SDK output |
| Internal flash | Samsung 8 GB eMMC; observed model string `8GTF4R` | user area is approximately 7456 MiB |
| eMMC interface | MMC 5.1-class device; stock configuration supports 8-bit, 1.8 V, HS400 up to 100 MHz | current deployment stores the adapted kernel and Ubuntu rootfs on eMMC; factory layout below is reference data, not a verified map of modified partitions |
| Bootloader | HiSilicon/HiSTB Fastboot `3.3.0` | U-Boot-derived shell; this is not Android USB fastboot |
| Stock SDK | `HiSTBAndroidV600R003C01SPC031_patch5` | factory software reference |
| Stock kernel | `3.18.24_hi3798mv310` | stock Android kernel/modules are reference material only and must not be loaded into the 4.4.35 kernel |
| Current project kernel | `4.4.35-HG680-KA` | Linux 4.4 vendor BSP, ARMv7/ARMHF |
| Current userspace | Ubuntu 22.04 LTS ARMHF | installed on internal eMMC for standalone DNS appliance deployment; USB-root remains a development/recovery option |
| Ethernet | integrated HiSilicon Fast Ethernet path | working; observed 100 Mbit/s full duplex |
| Wi-Fi / Bluetooth | MediaTek MT7668 SDIO combo module, 2 × 2 802.11ac + Bluetooth | validated on this unit; do not assume the Realtek/Fn-Link wiring found in generic SPC070 DTS files |
| Wi-Fi SDIO function | `037A:7608` | hardware validated |
| Bluetooth SDIO function | `037A:7668` | hardware validated |
| MT7668 SDIO operating point | 3.3 V, 4-bit, 50 MHz, SD High Speed | deliberately avoids UHS/CMD11 during the stable 4.4 bring-up |
| MT7668 Linux interfaces | `wlan0`, `p2p0`, `ap0` observed during bring-up | Wi-Fi Phase B completed |
| UART | `ttyAMA0`, 115200 baud | primary boot/recovery/debug console |
| USB | HiSilicon USB host + USB mass storage | working; non-destructive development/recovery boot path |
| TF / microSD | physical slot present | not required by the current eMMC deployment |
| HDMI | vendor HDMI/VO/PQ/TDE/HIFB stack | modules compile and dependency audit passes; runtime HDMI/fbcon bring-up is deferred for now |
| GPU | vendor configuration contains Mali-450 support | deferred together with the display path |
| RTC | no usable battery-backed RTC assumed by the project | Ubuntu image uses `fake-hwclock` + `chrony` |

The stock DDR configuration is particularly important when comparing boards. The HG-680-KA unit above uses a `1GB_16bitx2_4layers` DDR configuration, while the generic SPC070 MV310 SDK contains a different reference-board DDR topology. The deployed system still uses the existing HiSilicon Fastboot and factory DDR initialization, but its boot environment/arguments and eMMC kernel/rootfs contents have been changed. Do not mistake the preserved bootloader code for an unchanged factory boot configuration.

## Stock eMMC / Android partition layout

The stock Fastboot environment exposes the complete logical Linux partition map through `blkdevparts`:

```text
mmcblk0:
  4M(fastboot),
  4M(bootargs),
  12M(recovery),
  4M(deviceinfo),
  8M(baseparam),
  8M(pqparam),
  20M(logo),
  16M(fastplay),
  40M(kernel),
  20M(misc),
  40M(trustedcore),
  600M(backup),
  1024M(system),
  600M(cache),
  50M(private),
  8M(securestore),
  -(userdata)
```

Important alignment points from that map:

- `kernel` starts at **76 MiB** (`0x04C00000`). The factory `bootcmd` reads from MMC block `0x26000`, which is also exactly 76 MiB with 512-byte sectors.
- `system` starts at **776 MiB** and occupies 1024 MiB.
- `cache` starts at **1800 MiB** and occupies 600 MiB.
- `private` starts at **2400 MiB** and occupies 50 MiB.
- `securestore` starts at **2450 MiB** and occupies 8 MiB.
- `userdata` starts at **2458 MiB** and consumes the remainder of the eMMC user area.
- the Fastboot environment is at `0x00400000`, size `0x00010000`, i.e. the first 64 KiB of the logical `bootargs` region.

The complete per-partition start/end table, relevant factory environment, stock kernel load arithmetic and safety notes are documented in [`docs/hg680ka/boot-emmc-layout.md`](docs/hg680ka/boot-emmc-layout.md).

This logical map comes from the board's **factory** `bootargs` and documents the original Android partition enumeration. The running eMMC deployment has since installed a new kernel and rootfs, so this map **must not be assumed to describe the current writable filesystem or image locations**. The exact deployed layout and final Fastboot commands have not been published; do not infer flashing offsets from this stock map. eMMC `boot0`, `boot1`, RPMB, factory bootloader/auxiliary code, DDR initialization, trusted/secure storage and OTP/eFuse remain outside the documented flashing procedure.

### Generated USB development/recovery image

This is separate from the stock eMMC layout. The current generated removable USB image uses:

| Partition | Filesystem | Label | Purpose |
| --- | --- | --- | --- |
| p1 | FAT32 | `HGBOOT` | 256 MiB boot partition containing the kernel/boot files |
| p2 | ext4 | `ubuntu-root` | Ubuntu 22.04 ARMHF root filesystem |

Keeping the USB layout documented separately avoids confusing the project-generated image with the historical factory partition map or the independently deployed eMMC system.

## Current software stack

- Vendor kernel: Linux `4.4.35`, board release `4.4.35-HG680-KA`.
- Current architecture: ARMv7 kernel/userspace ABI (`armhf`) using the HiSilicon `arm-histbv320-linux-` toolchain supplied with the SDK.
- Root filesystem: Ubuntu 22.04 LTS (Jammy) ARMHF, generated by GitHub Actions with `debootstrap`.
- Init/service manager: systemd.
- Network time: `chrony`; `fake-hwclock` provides a sane approximate time before the network is available.
- Bootloader: existing HiSilicon Fastboot 3.3.0; its stored boot arguments/environment were updated for standalone eMMC boot.
- Deployed storage: adapted kernel and Ubuntu rootfs on internal eMMC (actual write offsets/partitions not documented).
- Operational use: DNS caching/filtering on a private office network, approximately two weeks in service as of October 2026 (operator-reported).

USB-root boot was the original non-destructive bring-up path and remains useful for controlled tests and recovery. It is **not** the current deployment path. The eMMC migration does not imply that the factory bootloader binary or DDR initialization was replaced.

## Project progress

| Area | Status | Notes |
| --- | --- | --- |
| HG-680-KA board kernel profile | done | board-specific config layered over the vendor MV310 baseline; debug/unrelated drivers trimmed |
| Kernel build CI | done | GitHub Actions builds `hi_kernel.bin`, `uImage`, DTB and config |
| Ubuntu 22.04 ARMHF rootfs | done | reproducible debootstrap image |
| Directly writable USB image | done | FAT32 `HGBOOT` + ext4 `ubuntu-root` image generated by CI for development/recovery |
| Standalone eMMC boot | deployed | both kernel and Ubuntu rootfs installed on internal eMMC; modified Fastboot boot arguments; exact deployed layout not documented |
| DNS cache/filter appliance | in use | operating on a private office network for approximately two weeks as of October 2026; not a measured uptime/SLA claim |
| Ethernet | done | DHCP/IP networking used in board tests |
| SDIO Phase A | done | deterministic MT7668 enumeration, FN1 `037A:7608`, FN2 `037A:7668` |
| MT7668 Wi-Fi Phase B | done | 2.4/5 GHz STA, WPA2, DHCP/IP traffic; VHT80 2×2 link reported 866.5 Mbit/s PHY rate |
| MT7668 Bluetooth Phase C | done/integration | Linux-4.4-compatible MediaTek SDIO driver and stock patch/EEPROM path integrated |
| Wi-Fi/BT kernel-module packaging | done | modules installed under `/lib/modules/4.4.35-HG680-KA/extra/hg680ka/` and indexed by `depmod` |
| MT7668 stock firmware packaging | done in this branch | selected factory payload is hash-checked and installed into generated rootfs |
| HDMI console Phase A | deferred | `hi_pq`, `hi_hdmi`, `hi_vou`, `hi_tde`, `hi_fb` compile and dependency audit completed; PR #6 closed without merge and runtime board validation is paused |
| framebuffer console | deferred | paused together with HDMI/display bring-up |
| Mali/EGL/GLES | deferred | no current display/GPU bring-up is planned |
| Stock eMMC partition map | documented | complete 17-region `blkdevparts` layout recovered from the original Fastboot environment |
| Linux 6.18 ARM64 | planned | future official Linux 6.18.y + board patch series + TF-A/PSCI work; not a vendor 4.4 in-place upgrade |

More detailed Wi-Fi/Bluetooth and boot/eMMC notes are under `docs/hg680ka/`.

## Build the vendor 4.4 kernel

From the SDK root:

```sh
cp configs/hi3798mv310/HG-680-KA_cfg.mak cfg.mak
source ./env.sh
make linux -j"$(nproc)"
```

The board profile keeps the vendor MV310 configuration as its compatibility baseline and applies HG-680-KA-specific kernel configuration/DTS changes on top of it.

GitHub Actions also provides reproducible build jobs for the kernel, MT7668 drivers and Ubuntu system image. The system-image job produces:

- `hi_kernel.bin`
- `uImage`
- `hi3798mv310.dtb`
- final kernel `.config`
- Ubuntu 22.04 ARMHF rootfs tarball
- directly writable USB disk image

## Current eMMC installation (deployed status)

The original bring-up sequence used a USB-hosted kernel and root filesystem. The developer has since **flashed the adapted Linux kernel and Ubuntu 22.04 ARMHF rootfs to internal eMMC**, adjusted the existing Fastboot boot environment/command-line parameters with `setenv`, and confirmed **standalone boot from eMMC**. In October 2026 this unit was used as a DNS caching and filtering appliance for a private office network, with about two weeks of operational use at the time of reporting.

This records the observed deployment status, **not a general-purpose flashing guide**. The exact eMMC write offsets/partition layout, final persisted `bootcmd`/`bootargs`, and details of any firmware or filesystem migration are not captured in this repository. The stock `mmc read` offsets below and the USB boot arguments must not be copied as instructions for eMMC installation. No workplace IP addresses, domain lists, filtering rules, or administrative credentials are published here.

The existing vendor Fastboot and DDR initialization remain the starting point; the boot environment is no longer factory-default. See [the stock environment and deployed-status notes](docs/hg680ka/boot-emmc-layout.md) for the distinction.


## Non-destructive USB development/recovery boot

The stock Fastboot command loads the factory kernel to `0x1FFBFC0`; the project intentionally reuses the same RAM address for USB boot. With a generated project USB image inserted:

```text
usb start
fatls usb 0:1
fatload usb 0:1 0x01FFBFC0 hi_kernel.bin
setenv bootargs root=/dev/sda2 rootwait rw console=ttyAMA0,115200 loglevel=7
bootm 0x01FFBFC0
```

`fatls` is only a sanity check that `hi_kernel.bin` exists on the FAT partition. This is a **temporary USB boot example**, not the current eMMC deployment command line. Do not run `saveenv` while testing this recovery path. Reset/power-cycle restores whichever Fastboot environment is actually persisted on the board; on the currently deployed unit that is **not necessarily the original factory** `bootargs` or `bootcmd`.

The exact factory environment and partition/load-address derivation are in [`docs/hg680ka/boot-emmc-layout.md`](docs/hg680ka/boot-emmc-layout.md).

## MT7668 firmware

The original HG-680-KA firmware archive contains MediaTek and several unrelated Realtek firmware sets. This repository keeps only the payload relevant to the board's validated MT7668 combo device:

```text
EEPROM_MT7668.bin
EEPROM_MT7668_DMG.bin
EEPROM_MT7668_e1.bin
WIFI_RAM_CODE_MT7668.bin
WIFI_RAM_CODE2_SDIO_MT7668.bin
mt7668_patch_e1_hdr.bin
mt7668_patch_e2_hdr.bin
wifi.cfg
woble_setting.bin
```

The `rtl8723*`, `rtl8761*` and `rtl8822*` files from the same factory package are not included because they do not correspond to this board's `037A:7608` / `037A:7668` SDIO device.

Firmware provenance, exact hashes and the archive format are documented in `firmware/hg680ka/mt7668/README.md`. The installer performs archive-level and per-file SHA-256 verification before files are copied to a root filesystem.

## Driver and patch provenance

The repository intentionally records where non-trivial board support came from instead of presenting all changes as original SPC070 code.

### HG-680-KA board support

The kernel configuration cleanup, HG-680-KA board profile, DTS corrections, SDIO power/detect helper and image-packaging changes are project-specific changes in this repository, based on the HiSilicon SPC070 vendor Linux 4.4 BSP.

### MT7668 Wi-Fi

SPC070 no longer carries the MT7668BS Wi-Fi driver tree needed by this board. The out-of-tree build therefore uses the closely related HiSilicon SPC060 source:

```text
Repository: https://github.com/07bug/HiSTBLinuxV100R005C00SPC060.git
Commit:     a9f05973129d738e175416dd4a91b2c264ffcdd4
Path:       source/component/wifi/drv/sdio_mt7668bs
```

`scripts/hg680ka/build-mt7668-wifi.sh` pins that exact revision and builds it against the local `4.4.35-HG680-KA` kernel rather than loading the stock Android 3.18 module.

### MT7668 Bluetooth

The Bluetooth-over-SDIO driver is built from MediaTek-derived GPLv2 code published by Google Coral:

```text
Repository: https://coral.googlesource.com/mt7668-bluetooth-mod
Commit:     040ca262f203faec9f1337db5b1b991cfba72ecf
```

That revision is intentionally pinned before Coral commit `dbf041d`, which introduced use of `hci_dev::hw_info`; that member is absent from the HG-680-KA vendor Linux 4.4.35 Bluetooth core. The selected revision already includes the relevant Linux-4.4 compatibility work.

### HDMI / framebuffer / video output

The vendor HDMI path remains available in the SPC070 MSP implementation (PQ, HDMI, VO, TDE and HIFB). A Phase A branch verified that these modules compile and that their dependency graph can be audited, but runtime HDMI/fbcon bring-up is deferred for now. PR #6 was closed without merge; the vendor display stack is retained as a reference and can be revisited later if display output becomes a priority. No claim is made that this proprietary MSP stack is equivalent to an upstream DRM/KMS driver.

### Future Linux 6.18 ARM64 work

The planned ARM64 port will use official stable Linux 6.18.y as the kernel base. Existing upstream HiSilicon support such as Hi3798CV200/related CRG, MMC, USB and PHY drivers, together with Trusted Firmware-A's HiSilicon Poplar PSCI/GICv2 implementation, are architectural references for the MV310 port. They are not treated as drop-in HG-680-KA support.

The intended model is a reviewable HG-680-KA/MV310 patch series on top of upstream Linux/TF-A rather than copying the complete vendor 4.4 driver tree into a modern kernel.

## Repository layout

```text
configs/hi3798mv310/                 board SDK configuration
source/kernel/linux-4.4.y/           vendor Linux 4.4 kernel tree
scripts/hg680ka/                     board build/install helpers
docs/hg680ka/                        hardware bring-up notes
firmware/hg680ka/mt7668/             selected stock MT7668 firmware + hashes
.github/workflows/                    reproducible kernel/driver/system-image CI
```

## Safety / recovery rules

For new board bring-up or unverified hardware, prefer RAM/USB boot and read-only hardware archaeology. The current unit has already undergone an intentional kernel/rootfs eMMC installation and Fastboot environment changes; these are not recommended as generic copy-and-paste operations. In particular:

- do not use `saveenv` merely to test a boot argument or overwrite a deployed boot configuration without a verified backup/recovery plan;
- do not blindly `mmc write` a kernel/rootfs to eMMC based on factory partition offsets;
- do not overwrite eMMC boot0/boot1, RPMB, bootloader or DDR-init regions;
- do not write SoC OTP/eFuse or MT7668 eFuse/calibration data;
- do not load stock Android Linux 3.18 kernel modules into the 4.4.35 kernel;
- keep a UART recovery path available before experimenting with persistent boot changes.

The USB image's helper script is for writing the generated image to a **removable USB drive**, not to the HG-680-KA's internal eMMC. It is not the procedure used for the deployed eMMC appliance.

## Documentation

- `docs/hg680ka/boot-emmc-layout.md` — original Fastboot environment/eMMC map, deployed eMMC status, and separate USB recovery boot path.
- `docs/hg680ka/phase-b.md` — MT7668 Wi-Fi bring-up and validation.
- `docs/hg680ka/phase-c.md` — MT7668 Bluetooth-over-SDIO work.
- `firmware/hg680ka/mt7668/README.md` — selected factory firmware, hashes and installation model.

This repository remains a bring-up/development BSP. Treat status marked *in progress*, *build complete* or *deferred* separately from hardware-tested functionality.
