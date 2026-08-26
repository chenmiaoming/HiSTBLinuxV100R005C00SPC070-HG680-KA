# HG-680-KA ARM64 bring-up

This document tracks the non-destructive ARM64 bring-up for the FiberHome HG-680-KA / Hi3798MV310-family SoC. The long-term target is Linux 6.18.y on AArch64 with a reviewable TF-A and kernel patch series. The factory DDR initialization and installed Fastboot image are deliberately left untouched while the low-level handoff is being validated.

## Phase ARM64-A: validate the EL3 handoff first

The first milestone deliberately does not boot Linux. It proves the smaller chain:

```text
BootROM / factory DDR init
        -> factory AArch32 HiSilicon Fastboot
        -> FIP loader
        -> AArch64 BL31 at EL3
        -> position-independent AArch64 BL33 UART smoke payload
```

The SPC070 sources already contain a vendor TF-A 1.2 port for Hi3798MV200 plus an MV310 AArch64 boot stub and ARM64 Linux DTS. The following register-level facts line up between those paths and are the basis for the initial MV310 TF-A platform instance:

- AArch64 mode register: `0xf8a80030`
- CPU RVBAR register: `0xf8a80034`
- CPU low-power control: `0xf8a22048`
- CPU reset control: `0xf8a22050`
- GICv2 distributor / CPU interface: `0xf1001000` / `0xf1002000`
- architectural counter frequency: 24 MHz
- UART0: `0xf8b00000`, 115200 baud, 75 MHz input clock on the ASIC path
- non-TEE BL31 load/link address: `0x04400000`

The initial `plat/hisilicon/hi3798mv310` directory is intentionally seeded from the vendor Hi3798MV200 TF-A platform. It is a hardware-validation baseline, not the final upstreamable implementation. Once the board proves the AArch64/PSCI path, the platform logic will be moved onto a current upstream TF-A baseline and the old vendor entry ABI will be isolated or removed.

## Build

Run:

```sh
bash scripts/hg680ka/build-arm64-atf-smoke.sh
```

The script uses the SDK's bundled GCC 5.1 AArch64 toolchain, builds only TF-A BL31, creates a small position-independent BL33 payload, appends a valid DTB after its legacy ARM64 uImage, and packages BL31 + BL33 into the FIP format understood by `source/boot/fastboot/common/load_fip.c`.

The BL33 payload does not use a stack and does not assume a fixed RAM address. That is important because the vendor FIP loader enters ARM64 BL33 at the uImage payload's in-place address inside the loaded FIP rather than relocating the payload to the uImage load address.

## First board test

Keep the factory eMMC bootloader and environment unchanged. Copy `hg680ka-arm64-smoke.fip` from the CI artifact to the FAT partition of the development USB drive, then from the factory Fastboot prompt use a temporary RAM load:

```text
usb start
fatls usb 0:1
fatload usb 0:1 0x02000000 hg680ka-arm64-smoke.fip
bootm 0x02000000
```

Do not run `saveenv` and do not write the FIP to eMMC during this phase.

There are two useful outcomes:

1. If the factory Fastboot was built with `CONFIG_ARM64_SUPPORT`, `bootm` should identify the FIP, print the BL31/BL33 table, copy BL31 to `0x04400000`, select AArch64 mode, and warm-reset into BL31. The final UART output should include a line similar to:

   ```text
   HG680KA ARM64 BL33 smoke: CurrentEL=EL1
   AArch64 handoff reached; waiting in WFI.
   ```

   `EL1` is expected for the vendor FIP ABI because `load_fip.c` currently constructs the ARM64 BL33 SPSR with `MODE_EL1`. A later upstream TF-A/Linux path should normally preserve EL2 for Linux.

2. If `bootm` rejects the FIP before `load_fip()` runs, the installed factory Fastboot likely lacks `CONFIG_ARM64_SUPPORT`. That is still a useful result: the next milestone becomes a RAM-only AArch32-to-AArch64 transition helper using the existing MV310 `arm64_boot` code rather than modifying the installed bootloader.

## Exit criteria before Linux 6.18

Phase ARM64-A is complete when the board can reliably reach AArch64 non-secure BL33 through an EL3 runtime and TF-A PSCI `CPU_ON` can release CPUs 1-3. Only after that should the minimal Linux 6.18 DTS/kernel phase add UART, timer, GIC and PSCI, followed by clocks/reset, eMMC, USB, Ethernet and SDIO in separate steps.
