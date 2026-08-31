#!/usr/bin/env python3
"""Apply the HG680-KA late-secondary diagnostic fast path.

Earlier board tests already proved all of the following on CPU1:
  * PSCI/TF-A CPU release and Cortex-A53 SMPEN
  * init_kernel_el() and __cpu_setup()
  * stage-1 MMU enable and __enable_mmu() return
  * TTBR1 high-VA kernel instruction fetch

Do not keep those old A/B/C/P/D/E/U-Z UART probes in the image: each probe
expands to a polling PL011 sequence and consumes scarce .idmap.text space.
Linux arm64 enforces that the complete idmap text fits in one 4 KiB page.

This revision therefore changes only the still-unknown boundary after
__enable_mmu():
  * install a compact, stackless EL1 synchronous-exception catcher in idmap;
  * temporarily bypass secondary boot-mode/EL2 bookkeeping already known to
    be redundant for this Cortex-A53, KVM-disabled diagnostic image;
  * load secondary_data.task, establish the secondary stack, restore normal
    vectors, and enter secondary_start_kernel();
  * print N<cpu> with MMU off if secondary_data.task is unexpectedly zero;
  * print !<cpu> plus ESR_EL1/ELR_EL1/FAR_EL1 if an early synchronous exception
    occurs before the normal kernel vector table is restored.

The catcher emits only the Current-EL-with-SPx synchronous vector slot at
VBAR+0x200. IRQ/FIQ/SError are masked during this early path, so a full 2 KiB
vector table is unnecessary.
"""

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def instrument_head(path: Path) -> None:
    text = path.read_text()

    helpers = r'''
/* HG680-KA MMU-off diagnostic UART helpers. Used only on failure paths. */
	.macro	hg680ka_uart_putc_reg, reg
	movz	x9, #0xf8b0, lsl #16
991:	ldr	w11, [x9, #0x18]
	tbnz	w11, #5, 991b
	str	\reg, [x9]
	.endm

	.macro	hg680ka_uart_cpu_tag, ch
	mov	w10, #\ch
	hg680ka_uart_putc_reg w10
	mrs	x10, mpidr_el1
	and	w10, w10, #0xff
	add	w10, w10, #'0'
	hg680ka_uart_putc_reg w10
	mov	w10, #' '
	hg680ka_uart_putc_reg w10
	.endm

	.macro	hg680ka_uart_hex64, src
	mov	x6, #60
992:	lsrv	x5, \src, x6
	and	w5, w5, #0xf
	cmp	w5, #9
	add	w4, w5, #'0'
	add	w5, w5, #('a' - 10)
	csel	w4, w4, w5, ls
	hg680ka_uart_putc_reg w4
	subs	x6, x6, #4
	b.pl	992b
	.endm
'''

    text = replace_once(
        text,
        '#include "efi-header.S"\n',
        '#include "efi-header.S"\n' + helpers,
        "diagnostic UART helpers",
    )

    # Keep the normal secondary path untouched until __enable_mmu() has
    # returned. All earlier boundaries have already been demonstrated on-board.
    text = replace_once(
        text,
        '\tadrp\tx2, idmap_pg_dir\n\tbl\t__enable_mmu\n\tldr\tx8, =__secondary_switched\n\tbr\tx8\n',
        '''\tadrp\tx2, idmap_pg_dir
\tbl\t__enable_mmu

\t/* TTBR0 still identity-maps .idmap.text. Install a low-runtime-address
\t * synchronous catcher before jumping to the normal high-VA text. */
\tadrp\tx17, hg680ka_diag_vectors
\tadd\tx17, x17, :lo12:hg680ka_diag_vectors
\tmsr\tvbar_el1, x17
\tisb
\tadrp\tx18, hg680ka_diag_no_task
\tadd\tx18, x18, :lo12:hg680ka_diag_no_task

\tldr\tx8, =__secondary_switched
\tbr\tx8
''',
        "post-MMU catcher install",
    )

    old_switched = '''SYM_FUNC_START_LOCAL(__secondary_switched)
\tmov\tx0, x20
\tbl\tset_cpu_boot_mode_flag

\tmov\tx0, x20
\tbl\tfinalise_el2

\tstr_l\txzr, __early_cpu_boot_status, x3
\tadr_l\tx5, vectors
\tmsr\tvbar_el1, x5
\tisb

\tadr_l\tx0, secondary_data
\tldr\tx2, [x0, #CPU_BOOT_TASK]
\tcbz\tx2, __secondary_too_slow

\tinit_cpu_task x2, x1, x3

#ifdef CONFIG_ARM64_PTR_AUTH
\tptrauth_keys_init_cpu x2, x3, x4, x5
#endif

\tbl\tsecondary_start_kernel
\tASM_BUG()
SYM_FUNC_END(__secondary_switched)
'''

    new_switched = '''SYM_FUNC_START_LOCAL(__secondary_switched)
\t/* HG680-KA direct bring-up diagnostic. The board has already proven
\t * identical EL2 entry and this Cortex-A53 has no VHE. In this KVM-disabled
\t * image, skip the secondary-only bookkeeping stores/HVC and get directly
\t * to the task pointer CPU0 prepared for this CPU. */
\tadr_l\tx0, secondary_data
\tldr\tx2, [x0, #CPU_BOOT_TASK]
\tcbnz\tx2, 1f
\tbr\tx18
1:
\tinit_cpu_task x2, x1, x3

#ifdef CONFIG_ARM64_PTR_AUTH
\tptrauth_keys_init_cpu x2, x3, x4, x5
#endif

\t/* The secondary task/stack now exists; normal exception handling is safe. */
\tadr_l\tx5, vectors
\tmsr\tvbar_el1, x5
\tisb

\tbl\tsecondary_start_kernel
\tASM_BUG()
SYM_FUNC_END(__secondary_switched)
'''
    text = replace_once(text, old_switched, new_switched, "direct __secondary_switched")

    catcher = r'''

/*
 * HG680-KA stackless early-secondary synchronous catcher.
 * VBAR is 2 KiB aligned. Only Current EL with SPx synchronous (+0x200) is
 * needed while DAIF masks asynchronous exceptions.
 */
	.align	11
hg680ka_diag_vectors:
	.space	0x200
	b	hg680ka_diag_exception

hg680ka_diag_exception:
	mrs	x0, esr_el1
	mrs	x1, elr_el1
	mrs	x2, far_el1
	mrs	x12, sctlr_el1
	bic	x12, x12, #SCTLR_ELx_M
	pre_disable_mmu_workaround
	msr	sctlr_el1, x12
	isb

	hg680ka_uart_cpu_tag 0x21		// !<cpu>
	mov	w4, #'E'
	hg680ka_uart_putc_reg w4
	mov	w4, #'='
	hg680ka_uart_putc_reg w4
	hg680ka_uart_hex64 x0
	mov	w4, #' '
	hg680ka_uart_putc_reg w4
	mov	w4, #'L'
	hg680ka_uart_putc_reg w4
	mov	w4, #'='
	hg680ka_uart_putc_reg w4
	hg680ka_uart_hex64 x1
	mov	w4, #' '
	hg680ka_uart_putc_reg w4
	mov	w4, #'F'
	hg680ka_uart_putc_reg w4
	mov	w4, #'='
	hg680ka_uart_putc_reg w4
	hg680ka_uart_hex64 x2
	mov	w4, #'\r'
	hg680ka_uart_putc_reg w4
	mov	w4, #'\n'
	hg680ka_uart_putc_reg w4
998:	wfe
	b	998b

hg680ka_diag_no_task:
	mrs	x12, sctlr_el1
	bic	x12, x12, #SCTLR_ELx_M
	pre_disable_mmu_workaround
	msr	sctlr_el1, x12
	isb
	hg680ka_uart_cpu_tag 0x4e		// N<cpu>
997:	wfe
	b	997b
'''

    # head.S ends in .idmap.text after __primary_switch, so putting the catcher
    # here avoids padding holes in the middle of live idmap routines.
    text = replace_once(
        text,
        'SYM_FUNC_END(__primary_switch)',
        'SYM_FUNC_END(__primary_switch)' + catcher,
        "compact idmap catcher",
    )

    path.write_text(text)

    required = (
        "hg680ka_diag_vectors",
        "hg680ka_diag_exception",
        "hg680ka_diag_no_task",
        "hg680ka_uart_hex64 x0",
        "cbnz\tx2, 1f",
        "bl\tsecondary_start_kernel",
        ".space\t0x200",
    )
    for needle in required:
        if needle not in text:
            raise SystemExit(f"failed to insert required diagnostic: {needle}")

    # The obsolete success-path UART markers must stay gone; they were large
    # enough to make the one-page idmap constraint difficult to satisfy.
    for obsolete in ("0x41", "0x42", "0x43", "0x44", "0x45", "0x50",
                     "hg680ka_setup_marker"):
        if obsolete in text:
            raise SystemExit(f"obsolete early marker unexpectedly present: {obsolete}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <arch/arm64/kernel/head.S>")

    head = Path(sys.argv[1])
    instrument_head(head)
    print(f"instrumented {head} with compact HG680-KA fault catcher/direct bring-up")


if __name__ == "__main__":
    main()
