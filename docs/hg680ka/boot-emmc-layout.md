# HG-680-KA stock Fastboot environment and eMMC layout

This document records the stock boot environment observed on the HG-680-KA development unit used by this repository. It is intended as a board-alignment and recovery reference.

The values below were captured from the board's original HiSilicon/HiSTB Fastboot shell. The project does **not** require modifying or replacing the stock bootloader.

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

`0x00400000` is exactly 4 MiB, so the 64 KiB Fastboot environment sits at the beginning of the logical `bootargs` region (`mmcblk0p2`). This project does not write it during normal development.

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

This confirms why the project's non-destructive USB boot path also uses `0x1FFBFC0`: it preserves the factory kernel load address while changing only the source from raw eMMC to the FAT USB partition.

## Non-destructive USB boot

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

The `setenv bootargs ...` command is intentionally temporary. **Do not run `saveenv`.** A power cycle or reset restores the factory environment values.

The minimal USB boot arguments intentionally omit the stock Android `blkdevparts` string because the generated system does not need the eMMC partitions in order to boot. If read-only access to the factory Android partitions is needed for archaeology, the original `blkdevparts` definition above can be supplied explicitly after boot planning and verification.

## Safety boundaries

Normal project bring-up must not write:

- the factory Fastboot / auxiliary boot code;
- the Fastboot environment at `0x00400000`;
- eMMC `boot0` / `boot1`;
- RPMB;
- `trustedcore`, `private`, or `securestore` merely to test Linux;
- DDR initialization data;
- SoC OTP/eFuse;
- MT7668 OTP/eFuse/calibration storage.

Prefer USB-root boot until an eMMC installation design is reviewed independently from the factory partition layout.
