CROSS_COMPILE ?= aarch64-linux-gnu-
OUT ?= build

CC      := $(CROSS_COMPILE)gcc
LD      := $(CROSS_COMPILE)ld
OBJCOPY := $(CROSS_COMPILE)objcopy
DTC     ?= dtc
MKIMAGE ?= mkimage

.PHONY: all clean

all: $(OUT)/bl33.bin

$(OUT):
	mkdir -p $@

$(OUT)/start.o: start.S | $(OUT)
	$(CC) -c -nostdinc -ffreestanding -march=armv8-a -D__ASSEMBLY__ $< -o $@

$(OUT)/smoke.elf: $(OUT)/start.o smoke.lds
	$(LD) -nostdlib --build-id=none -T smoke.lds $< -o $@

$(OUT)/smoke.bin: $(OUT)/smoke.elf
	$(OBJCOPY) -O binary $< $@

$(OUT)/smoke.dtb: smoke.dts | $(OUT)
	$(DTC) -I dts -O dtb -o $@ $<

$(OUT)/smoke.uImage: $(OUT)/smoke.bin
	$(MKIMAGE) -A arm64 -O linux -T kernel -C none -a 0 -e 0 \
		-n 'HG680KA ARM64 BL33 smoke' -d $< $@

# The vendor load_fip() expects the FDT immediately after image_get_image_end()
# of the ARM64 legacy uImage, so the DTB is deliberately outside the uImage
# payload length but inside the BL33 FIP entry.
$(OUT)/bl33.bin: $(OUT)/smoke.uImage $(OUT)/smoke.dtb
	cat $^ > $@

clean:
	rm -rf $(OUT)
