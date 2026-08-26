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
        }

        /DISCARD/ : {
                *(.comment*)
                *(.note*)
                *(.eh_frame*)
        }
}
