# HG-680-KA board profile
#
# Keep the vendor MV310 profile as the baseline and layer board-specific
# overrides on top.  This keeps the original SDK configuration intact while
# giving this fork a stable board configuration name.
#
# IMPORTANT: the inherited vendor profile still contains the vendor reference
# DDR/boot regfile.  We currently use this profile only for `make linux`; do
# not use it to replace the stock HG-680-KA Fastboot/DDR initialization.

include configs/hi3798mv310/hi3798mv31dmg_hi3798mv310_cfg.mak

# Give build outputs a board-specific directory.
CFG_HI_OUT_DIR=HG-680-KA

# Start from the vendor SoC defconfig, then merge our board/server fragment.
# Linux 4.4 Kconfig accepts multiple goals here: the first creates .config and
# the second (%.config) merges arch/arm/configs/hg680-ka.config.
CFG_HI_KERNEL_CFG=hi3798mv310_defconfig hg680-ka.config
