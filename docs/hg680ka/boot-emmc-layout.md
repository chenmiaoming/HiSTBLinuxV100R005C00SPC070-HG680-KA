# HG-680-KA factory Fastboot layout, deployed eMMC boot and USB recovery

This document separates the **original factory** bootloader/environment and partition map from the board's **current eMMC deployment**, plus the original USB development/recovery workflow.

The factory values below were captured before installing the adapted system. The board now has **both the custom Linux 4.4.35 kernel and Ubuntu 22.04 ARMHF rootfs on internal eMMC**, and its Fastboot boot arguments/environment were modified for autonomous startup. The existing vendor Fastboot and DDR initialization are retained, but the stored environment and eMMC contents are no longer assumed factory-default. Exact new partition offsets and the final persisted environment have not been published.

## Bootloader / storage fingerprint

Observed at boot:

```text
Fastboot 3.3.0
CPU:        Hi3798Mv310
Boot Media: eMMC
DDR Size:   1GB

MMC model:  8GTF4R
MMC size:   7456M
MMC:        5.1
Speed:      100000000 Hz
Mode:       HS400
Voltage:    1.8V
Bus width:  8bit

Boot Env Offset: 0x00400000
Boot Env Size:   0x00010000

SDK Version: HiSTBAndroidV600R003C01SPC031_patch5
```

The DDR auxiliary code reports:

```text
DDR code - V1.1.2.1 20171011
Reg Name: hi3798m31dmd_hi3798mv310_DDR3-1866_1GB_16bitx2_4layers.reg
```

This DDR topology is a key board fingerprint and should be compared before reusing this repository on another HG-680-KA variant.

## Relevant stock Fastboot environment

The original environment contains:

```text
bootdelay=0
verify=n
baudrate=115200

bootcmd=mmc read 0 0x1FFBFC0 0x26000 0x5000; bootm 0x1FFBFC0

bootargs=console=ttyAMA0,115200 blkdevparts=mmcblk0:4M(fastboot),4M(bootargs),12M(recovery),4M(deviceinfo),8M(baseparam),8M(pqparam),20M(logo),16M(fastplay),40M(kernel),20M(misc),40M(trustedcore),600M(backup),1024M(system),600M(cache),50M(private),8M(securestore),-(userdata) quiet

bootargs_512M=mem=512M mmz=ddr,0,0,44M
bootargs_768M=mem=768M mmz=ddr,0,0,44M
bootargs_1G=mem=1G mmz=ddr,0,0,44M
bootargs_2G=mem=2G mmz=ddr,0,0,44M
bootargs_3840M=mem=1G mmz=ddr,0,0,44M

stdin=serial
stdout=serial
stderr=serial
```

Network addresses and the unit's individual MAC address are intentionally omitted from this public reference because they are not needed for board alignment.

## Complete stock `blkdevparts` map

The factory `bootargs` provides the complete logical Linux partition definition for `mmcblk0`.

All starts below are cumulative offsets from the beginning of the eMMC user area.

| Linux partition | Name | Start | Size | End |
| ---: | --- | ---: | ---: | ---: |
| p1 | `fastboot` | 0 MiB (`0x00000000`) | 4 MiB | 4 MiB |
| p2 | `bootargs` | 4 MiB (`0x00400000`) | 4 MiB | 8 MiB |
| p3 | `recovery` | 8 MiB (`0x00800000`) | 12 MiB | 20 MiB |
| p4 | `deviceinfo` | 20 MiB (`0x01400000`) | 4 MiB | 24 MiB |
| p5 | `baseparam` | 24 MiB (`0x01800000`) | 8 MiB | 32 MiB |
| p6 | `pqparam` | 32 MiB (`0x02000000`) | 8 MiB | 40 MiB |
| p7 | `logo` | 40 MiB (`0x02800000`) | 20 MiB | 60 MiB |
| p8 | `fastplay` | 60 MiB (`0x03C00000`) | 16 MiB | 76 MiB |
| p9 | `kernel` | 76 MiB (`0x04C00000`) | 40 MiB | 116 MiB |
| p10 | `misc` | 116 MiB (`0x07400000`) | 20 MiB | 136 MiB |
| p11 | `trustedcore` | 136 MiB (`0x08800000`) | 40 MiB | 176 MiB |
| p12 | `backup` | 176 MiB (`0x0B000000`) | 600 MiB | 776 MiB |
| p13 | `system` | 776 MiB (`0x30800000`) | 1024 MiB | 1800 MiB |
| p14 | `cache` | 1800 MiB (`0x70800000`) | 600 MiB | 2400 MiB |
| p15 | `private` | 2400 MiB (`0x96000000`) | 50 MiB | 2450 MiB |
| p16 | `securestore` | 2450 MiB (`0x99200000`) | 8 MiB | 2458 MiB |
| p17 | `userdata` | 2458 MiB (`0x99A00000`) | remainder (`-`) | end of eMMC user area |

With the bootloader-reported 7456 MiB user area, `userdata` nominally occupies the remaining approximately 4998 MiB. Treat the factory `blkdevparts` string itself as the authoritative partition definition.

### Fastboot environment placement

The bootloader reports:

```text
Env Offset: 0x00400000
Env Size:   0x00010000
```

`0x00400000` is exactly 4 MiB, so the factory 64 KiB Fastboot environment sat at the beginning of the original logical `bootargs` region (`mmcblk0p2`). The current deployed system uses altered Fastboot environment settings; this stock address is **historical reference data**, not a claim that the deployed environment is unchanged or safe to overwrite.

## Stock kernel load path

The factory command is:

```text
mmc read 0 0x1FFBFC0 0x26000 0x5000
bootm 0x1FFBFC0
```

The block arguments use 512-byte MMC sectors:

- `0x26000` sectors = 155648 sectors = **76 MiB**, exactly the start of the `kernel` partition.
- `0x5000` sectors = 20480 sectors = **10 MiB** read into RAM.
- RAM load address = `0x1FFBFC0`.

This explains why the project's original USB boot path also uses `0x1FFBFC0`: it preserved the factory RAM load address while changing the kernel source to a FAT USB partition. These are **factory** read/load parameters; they do not establish the exact location or load command of the new eMMC-installed kernel.

## Current standalone eMMC deployment (October 2026)

The developer reports that the board was migrated from the non-destructive USB development workflow to an internally installed system:

- The adapted Linux 4.4.35-HG680-KA **kernel image has been flashed to eMMC**.
- The Ubuntu 22.04 ARMHF **root filesystem has also been installed on eMMC**.
- The existing HiSilicon Fastboot environment/boot command line was modified with `setenv` so the installed system can **boot independently without the USB development drive**.
- The board has operated for approximately **two weeks** as a **DNS cache and filtering service** in a private office network as of October 2026.

These are operator-reported deployment and usage facts, not proof of a particular filesystem partition number, boot-command string, continuous uptime, network throughput or service availability target. The original factory table above is **not an audited map of the currently deployed eMMC**. In particular, **do not infer** that the replacement kernel was written at the original 76 MiB kernel offset or that the Ubuntu rootfs occupies any particular original Android partition.

No final `bootcmd`, `bootargs`, `mmc write`, image-installation steps, device identifiers, DNS configuration or office network addresses are supplied. This document therefore **does not provide eMMC flash instructions**; a reproducible installation guide would require an independently verified new partition map and a recovery procedure.


## USB development/recovery boot (earlier workflow)

The generated USB image contains:

```text
p1  FAT32  label HGBOOT       256 MiB
p2  ext4   label ubuntu-root  root filesystem
```

At the stock Fastboot prompt:

```text
usb start
fatls usb 0:1
fatload usb 0:1 0x01FFBFC0 hi_kernel.bin
setenv bootargs root=/dev/sda2 rootwait rw console=ttyAMA0,115200 loglevel=7
bootm 0x01FFBFC0
```

Expected `fatload` behavior is to report the number of bytes read. If `fatls usb 0:1` cannot find `hi_kernel.bin`, stop and verify that the correct generated image was written to the USB drive.

The `setenv bootargs ...` command is intentionally temporary for this USB test. **Do not run `saveenv` merely to test recovery boot.** A power cycle or reset reloads the *persisted* Fastboot environment. On a device that has been migrated to eMMC boot, those values may already differ from the factory values recorded above.

The minimal USB boot arguments intentionally omit the stock Android `blkdevparts` string because the removable development image does not require eMMC for boot. The historical factory `blkdevparts` map should only be used as provenance, not as a safe replacement for the modified system's current partition description. Verify the actual device layout before even considering read-only archaeology.

## Safety boundaries

Fresh board bring-up or recovery testing must not blindly write:

- the factory Fastboot / auxiliary boot code;
- the Fastboot environment at the *factory-reported* `0x00400000` offset (the deployed environment has already been intentionally changed);
- eMMC `boot0` / `boot1`;
- RPMB;
- `trustedcore`, `private`, or `securestore` merely to test Linux;
- DDR initialization data;
- SoC OTP/eFuse;
- MT7668 OTP/eFuse/calibration storage.

USB-root boot remains a useful non-destructive test/recovery option. The existing eMMC installation is a real deployment, but it should not be reproduced on another board without first capturing the live `bootcmd`/`bootargs`, verifying its exact eMMC layout, backing up boot/recovery data, and checking board-revision compatibility.
