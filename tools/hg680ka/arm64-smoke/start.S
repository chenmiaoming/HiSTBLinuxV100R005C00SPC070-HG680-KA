/* SPDX-License-Identifier: GPL-2.0-or-later */

/*
 * Position-independent AArch64 BL33 payload for HG-680-KA.
 *
 * This validates the factory Fastboot -> BL31 -> non-secure EL2/EL1 handoff,
 * checks the Linux arm64 boot argument ABI, and then exercises PSCI_VERSION
 * plus CPU_ON for CPU1-CPU3. Keep the payload stackless and position
 * independent so the same image can be relocated by the vendor BL31 to the
 * uImage entry address at 0x00080000.
 */

.equ UART0_BASE_HI, 0xf8b0
.equ UART_FR,       0x18
.equ UART_FR_TXFF,  5

.section .text.boot, "ax"
.align  4
.global _start
.type   _start, %function
_start:
        /* Preserve the BL33 entry registers before any helper call clobbers them. */
        mov     x23, x0
        mov     x24, x1
        mov     x25, x2
        mov     x26, x3

        adr     x0, banner
        bl      puts

        mrs     x1, CurrentEL
        lsr     x1, x1, #2
        and     w0, w1, #0x3
        add     w0, w0, #48
        bl      putc

        adr     x0, boot_x0_prefix
        bl      puts
        mov     x0, x23
        bl      put_hex64
        adr     x0, boot_x1_prefix
        bl      puts
        mov     x0, x24
        bl      put_hex64
        adr     x0, boot_x2_prefix
        bl      puts
        mov     x0, x25
        bl      put_hex64
        adr     x0, boot_x3_prefix
        bl      puts
        mov     x0, x26
        bl      put_hex64
        adr     x0, newline
        bl      puts

        adr     x0, psci_version_prefix
        bl      puts
        movz    x0, #0x8400, lsl #16       /* PSCI_VERSION = 0x84000000 */
        smc     #0
        mov     x19, x0
        mov     x0, x19
        bl      put_hex64
        adr     x0, newline
        bl      puts

        /* CPU_ON_AARCH64(target_mpidr=1, secondary_entry, context_id=1). */
        movz    x0, #0x0003
        movk    x0, #0xc400, lsl #16
        movz    x1, #1
        adr     x2, secondary_entry
        movz    x3, #1
        smc     #0
        mov     x20, x0
        bl      settle_delay

        /* CPU_ON_AARCH64(target_mpidr=2, secondary_entry, context_id=2). */
        movz    x0, #0x0003
        movk    x0, #0xc400, lsl #16
        movz    x1, #2
        adr     x2, secondary_entry
        movz    x3, #2
        smc     #0
        mov     x21, x0
        bl      settle_delay

        /* CPU_ON_AARCH64(target_mpidr=3, secondary_entry, context_id=3). */
        movz    x0, #0x0003
        movk    x0, #0xc400, lsl #16
        movz    x1, #3
        adr     x2, secondary_entry
        movz    x3, #3
        smc     #0
        mov     x22, x0
        bl      settle_delay

        adr     x0, cpu1_result
        bl      puts
        mov     x0, x20
        bl      put_hex64
        adr     x0, newline
        bl      puts

        adr     x0, cpu2_result
        bl      puts
        mov     x0, x21
        bl      put_hex64
        adr     x0, newline
        bl      puts

        adr     x0, cpu3_result
        bl      puts
        mov     x0, x22
        bl      put_hex64
        adr     x0, done
        bl      puts

1:      wfi
        b       1b
.size _start, . - _start

/*
 * PSCI CPU_ON enters a non-secure AArch64 target with x0=context_id. CPU0 is
 * deliberately quiet for a short period after each CPU_ON, so the secondary
 * UART messages do not normally overlap one another.
 */
.align  4
.global secondary_entry
.type   secondary_entry, %function
secondary_entry:
        mov     x20, x0
        mrs     x21, mpidr_el1
        mrs     x22, CurrentEL

        adr     x0, secondary_prefix
        bl      puts
        add     w0, w20, #48
        bl      putc

        adr     x0, secondary_mpidr
        bl      puts
        mov     x0, x21
        bl      put_hex64

        adr     x0, secondary_el
        bl      puts
        lsr     x22, x22, #2
        and     w0, w22, #0x3
        add     w0, w0, #48
        bl      putc
        adr     x0, newline
        bl      puts

2:      wfi
        b       2b
.size secondary_entry, . - secondary_entry

/* Short serialization delay after CPU_ON; no architectural timer required. */
.type settle_delay, %function
settle_delay:
        movz    x14, #0x0100, lsl #16
3:      subs    x14, x14, #1
        b.ne    3b
        ret
.size settle_delay, . - settle_delay

/* x0: print 64-bit value as sixteen uppercase hexadecimal digits. */
.type put_hex64, %function
put_hex64:
        mov     x10, x30
        mov     x11, x0
        movz    x12, #16
4:      lsr     x13, x11, #60
        and     w0, w13, #0xf
        cmp     w0, #9
        add     w14, w0, #48
        add     w15, w0, #55
        csel    w0, w14, w15, ls
        bl      putc
        lsl     x11, x11, #4
        subs    x12, x12, #1
        b.ne    4b
        mov     x30, x10
        ret
.size put_hex64, . - put_hex64

/* x0: NUL-terminated string. No stack is used. */
.type puts, %function
puts:
        mov     x4, x0
        mov     x9, x30
5:      ldrb    w0, [x4], #1
        cbz     w0, 6f
        bl      putc
        b       5b
6:      mov     x30, x9
        ret
.size puts, . - puts

/* w0: byte to transmit. PL011 FR.TXFF is bit 5. */
.type putc, %function
putc:
        movz    x2, #0
        movk    x2, #UART0_BASE_HI, lsl #16
7:      ldr     w3, [x2, #UART_FR]
        tbnz    w3, #UART_FR_TXFF, 7b
        str     w0, [x2]
        ret
.size putc, . - putc

.section .rodata, "a"
banner:
        .asciz  "\r\nHG680KA ARM64 BL33 smoke: CurrentEL=EL"
boot_x0_prefix:
        .asciz  "\r\nBL33 boot args: x0=0x"
boot_x1_prefix:
        .asciz  " x1=0x"
boot_x2_prefix:
        .asciz  " x2=0x"
boot_x3_prefix:
        .asciz  " x3=0x"
psci_version_prefix:
        .asciz  "PSCI_VERSION=0x"
secondary_prefix:
        .asciz  "Secondary CPU"
secondary_mpidr:
        .asciz  " online: MPIDR=0x"
secondary_el:
        .asciz  " EL"
cpu1_result:
        .asciz  "CPU_ON(1)=0x"
cpu2_result:
        .asciz  "CPU_ON(2)=0x"
cpu3_result:
        .asciz  "CPU_ON(3)=0x"
done:
        .asciz  "\r\nPSCI multicore smoke complete; CPU0 waiting in WFI.\r\n"
newline:
        .asciz  "\r\n"
