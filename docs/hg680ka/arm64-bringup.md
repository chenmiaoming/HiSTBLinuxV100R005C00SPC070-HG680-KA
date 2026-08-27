# HG-680-KA ARM64 bring-up

This document tracks the non-destructive ARM64 bring-up for the FiberHome HG-680-KA / Hi3798MV310-family SoC. The long-term target is Linux 6.18.y on AArch64 with a reviewable TF-A and kernel patch series. The factory DDR initialization and installed Fastboot image are deliberately left untouched while the low-level handoff is being validated.

## Phase ARM64-A: validate the EL3 handoff first

The first milestone deliberately does not boot Linux. It proves the smaller chain:

```text
BootROM / factory DDR init
        -> factory AArch32 HiSilicon Fastboot
        -> FIP loader
        -> AArch64 BL31 at EL3
        -> non-secure AArch64 BL33 UART smoke payload
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
- vendor ARM64 Linux/BL33 destination: `0x00080000`
- vendor DTB relocation destination: `0x00010100`

The initial `plat/hisilicon/hi3798mv310` directory is intentionally seeded from the vendor Hi3798MV200 TF-A platform. It is a hardware-validation baseline, not the final upstreamable implementation. Once the board proves the AArch64/PSCI path, the platform logic will be moved onto a current upstream TF-A baseline and the old vendor entry ABI will be isolated or removed.

## Vendor Fastboot -> BL31 ABI

This BSP does not use an unmodified upstream TF-A BL2-to-BL31 handoff. The AArch32 Fastboot FIP loader writes the address of its `bl31_params_t` object to physical address `0x0` and a second platform argument to `0x8`, then requests an AArch64 warm reset. The vendor `bl31_entrypoint.S` explicitly reloads those two pointers from physical addresses `0x0` and `0x8` before calling `bl31_early_platform_setup()`.

For ARM64 BL33, Fastboot fills the parameter block as follows:

- `pc`: address of the legacy uImage payload inside the loaded FIP
- `arg0`: DTB immediately following the legacy uImage
- `arg1`: legacy uImage entry point
- `arg2`: BL33 FIP entry size minus the 64-byte legacy uImage header
- `arg4`: `CFG_BOOT_PARAMS + CONFIG_BOOT_PARAMS_MAX_SIZE`, i.e. `0x00010100`
- `arg5`: `CONFIG_DTB_MAX_SIZE`, i.e. `0x00020000`

The vendor BL31 then copies `arg2` bytes from `pc` to `arg1`, sets the eventual BL33 PC to `arg1`, and copies the DTB to `arg4`. Therefore the smoke uImage entry point must be a real writable/executable RAM address; zero is not valid. The project uses the vendor MV310 ARM64 kernel base `0x00080000`.

The build uses `SPD=none` and leaves `DISABLE_TEE=0`. Despite its name, this old vendor tree deliberately changes BL33 into Secure-world EL1 when `DISABLE_TEE=1` and skips the normal secure GIC setup. Keeping `DISABLE_TEE=0` without a BL32/SPD preserves the conventional TF-A model: BL31 in EL3 and BL33 in the non-secure world.

## Build

Run:

```sh
bash scripts/hg680ka/build-arm64-atf-smoke.sh
```

The script uses the SDK's bundled GCC 5.1 AArch64 toolchain, builds only TF-A BL31, creates a small position-independent BL33 payload, appends a valid DTB after its legacy ARM64 uImage, and packages BL31 + BL33 into the FIP format understood by `source/boot/fastboot/common/load_fip.c`.

The BL33 payload does not use a stack and uses only PC-relative references. BL31 relocates it to `0x00080000` before entry, so the same payload remains simple enough to diagnose the handoff without bringing Linux into the test.

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

1. If the factory Fastboot was built with `CONFIG_ARM64_SUPPORT`, `bootm` should identify the FIP, print the BL31/BL33 table, copy BL31 to `0x04400000`, select AArch64 mode, and warm-reset into BL31. BL31 should report a normal/non-secure exit, relocate BL33 to `0x00080000`, and the final UART output should include:

   ```text
   HG680KA ARM64 BL33 smoke: CurrentEL=EL1
   AArch64 handoff reached; waiting in WFI.
   ```

   `EL1` is expected for this first smoke payload because the vendor FIP loader constructs the ARM64 BL33 SPSR with `MODE_EL1`. Security state is separate from `CurrentEL`; with this build BL33 is expected to be non-secure EL1.

2. If `bootm` rejects the FIP before `load_fip()` runs, the installed factory Fastboot likely lacks `CONFIG_ARM64_SUPPORT`. That is still a useful result: the next milestone becomes a RAM-only AArch32-to-AArch64 transition helper using the existing MV310 `arm64_boot` code rather than modifying the installed bootloader.

## Exit criteria before Linux 6.18

Phase ARM64-A is complete when the board can reliably reach non-secure AArch64 BL33 through an EL3 runtime and TF-A PSCI `CPU_ON` can release CPUs 1-3. Only after that should the minimal Linux 6.18 DTS/kernel phase add UART, timer, GIC and PSCI, followed by clocks/reset, eMMC, USB, Ethernet and SDIO in separate steps.
