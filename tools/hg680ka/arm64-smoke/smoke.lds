OUTPUT_FORMAT("elf64-littleaarch64")
OUTPUT_ARCH(aarch64)
ENTRY(_start)

SECTIONS
{
        . = 0;
        .text : {
                KEEP(*(.text.boot))
                *(.text*)
        }
        .rodata : {
                *(.rodata*)
                /*
                 * Fastboot load_fip() places the FDT immediately after
                 * image_get_image_end().  Its old ARM32 libfdt accesses the
                 * fdt_header as native 32-bit words, so keep the trailing
                 * uImage payload 8-byte aligned.  The 64-byte legacy uImage
                 * header is already 8-byte aligned, which makes the following
                 * DTB pointer aligned as well.
                 */
                . = ALIGN(8);
        }

        /DISCARD/ : {
                *(.comment*)
                *(.note*)
                *(.eh_frame*)
        }
}
