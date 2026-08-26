/* SPDX-License-Identifier: GPL-2.0-or-later */

/*
 * Minimal position-independent AArch64 BL33 payload for HG-680-KA.
 *
 * The vendor Fastboot FIP loader enters BL33 at the address of the legacy
 * uImage payload inside the FIP buffer rather than relocating it to the uImage
 * load address. Keep this image position independent and avoid a stack.
 */

.equ UART0_BASE_HI, 0xf8b0
.equ UART_FR,       0x18
.equ UART_FR_TXFF,  5

.section .text.boot, "ax"
.align  4
.global _start
.type   _start, %function
_start:
        adr     x0, banner
        bl      puts

        mrs     x1, CurrentEL
        lsr     x1, x1, #2
        and     w0, w1, #0x3
        add     w0, w0, #48
        bl      putc

        adr     x0, suffix
        bl      puts

1:      wfi
        b       1b
.size _start, . - _start

/* x0: NUL-terminated string. No stack is used. */
.type puts, %function
puts:
        mov     x4, x0
        mov     x9, x30
2:      ldrb    w0, [x4], #1
        cbz     w0, 3f
        bl      putc
        b       2b
3:      mov     x30, x9
        ret
.size puts, . - puts

/* w0: byte to transmit. PL011 FR.TXFF is bit 5. */
.type putc, %function
putc:
        movz    x2, #0
        movk    x2, #UART0_BASE_HI, lsl #16
4:      ldr     w3, [x2, #UART_FR]
        tbnz    w3, #UART_FR_TXFF, 4b
        str     w0, [x2]
        ret
.size putc, . - putc

.section .rodata, "a"
banner:
        .asciz  "\r\nHG680KA ARM64 BL33 smoke: CurrentEL=EL"
suffix:
        .asciz  "\r\nAArch64 handoff reached; waiting in WFI.\r\n"
