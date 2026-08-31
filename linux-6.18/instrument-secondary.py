#!/usr/bin/env python3
"""Instrument HG680-KA arm64 secondary bring-up with an early fault catcher.

The board tests have already proved that CPU1 reaches __cpu_setup(), enables
stage-1 translation, returns from __enable_mmu(), and can fetch/execute normal
TTBR1 kernel text.  The remaining failure is therefore after the branch to
__secondary_switched.

This diagnostic stops adding post-MMU memory breadcrumbs.  Instead it installs
a 2 KiB-aligned, stackless EL1 vector table in .idmap.text before jumping to
high VA.  Any early synchronous exception can then return to the identity map,
disable translation, and print ESR_EL1/ELR_EL1/FAR_EL1 through the physical
PL011 without depending on kernel mappings or a stack.

For this Cortex-A53/KVM-disabled bring-up image, secondary-only bookkeeping
that is not required to enter secondary_start_kernel() is temporarily bypassed:
set_cpu_boot_mode_flag(), finalise_el2(), and the early boot-status clear.  The
firmware has already shown every CPU entering through EL2, and Cortex-A53 has
no VHE.  If secondary_data.task is unexpectedly zero, the CPU returns to the
idmap and prints N<cpu> instead of silently parking.
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

    macros = r'''
/* HG680-KA MMU-off UART helpers. */
	.macro	hg680ka_uart_putc_reg, reg
	movz	x9, #0xf8b0, lsl #16
991:	ldr	w11, [x9, #0x18]
	tbnz	w11, #5, 991b
	str	\reg, [x9]
	.endm

	.macro	hg680ka_uart_marker, ch
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
        '#include "efi-header.S"\n' + macros,
        "head diagnostic macros",
    )

    text = replace_once(
        text,
        'SYM_FUNC_START(secondary_entry)\n\tmov\tx0, xzr\n\tbl\tinit_kernel_el\t\t\t// w0=cpu_boot_mode\n',
        'SYM_FUNC_START(secondary_entry)\n\thg680ka_uart_marker 0x41\n\tmov\tx0, xzr\n\tbl\tinit_kernel_el\t\t\t// w0=cpu_boot_mode\n\thg680ka_uart_marker 0x42\n',
        "secondary_entry",
    )

    text = replace_once(
        text,
        'SYM_FUNC_START_LOCAL(secondary_startup)\n\t/*\n\t * Common entry point for secondary CPUs.\n\t */\n\tmov\tx20, x0\t\t\t\t// preserve boot mode\n',
        'SYM_FUNC_START_LOCAL(secondary_startup)\n\t/*\n\t * Common entry point for secondary CPUs.\n\t */\n\tmov\tx20, x0\t\t\t\t// preserve boot mode\n\thg680ka_uart_marker 0x43\n',
        "secondary_startup",
    )

    text = replace_once(
        text,
        '\tbl\t__cpu_setup\t\t\t// initialise processor\n\tadrp\tx1, swapper_pg_dir\n',
        '\thg680ka_uart_marker 0x50\n\tbl\t__cpu_setup\t\t\t// initialise processor\n\thg680ka_uart_marker 0x44\n\tadrp\tx1, swapper_pg_dir\n',
        "call __cpu_setup",
    )

    text = replace_once(
        text,
        '\tadrp\tx2, idmap_pg_dir\n\tbl\t__enable_mmu\n\tldr\tx8, =__secondary_switched\n\tbr\tx8\n',
        '''\tadrp\tx2, idmap_pg_dir
\thg680ka_uart_marker 0x45
\tbl\t__enable_mmu

\t/* Translation is now on, but TTBR0 still maps .idmap.text. Install a
\t * stackless low-VA catcher before entering normal kernel VA. */
\tadrp\tx17, hg680ka_diag_vectors
\tadd\tx17, x17, :lo12:hg680ka_diag_vectors
\tmsr\tvbar_el1, x17
\tisb
\tadrp\tx18, hg680ka_diag_no_task
\tadd\tx18, x18, :lo12:hg680ka_diag_no_task

\tldr\tx8, =__secondary_switched
\tbr\tx8
''',
        "post-MMU diagnostic vectors",
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
\t/* HG680-KA direct bring-up diagnostic.
\t *
\t * CPU0 already established the boot mode; all tested secondaries enter
\t * through EL2, and this Cortex-A53 has no VHE. Avoid the early secondary
\t * bookkeeping calls for this diagnostic and get directly to the first
\t * required shared-data load. The stackless idmap VBAR remains installed
\t * until init_cpu_task has established a valid secondary stack. */
\tadr_l\tx0, secondary_data
\tldr\tx2, [x0, #CPU_BOOT_TASK]
\tcbnz\tx2, 1f
\tbr\tx18
1:
\tinit_cpu_task x2, x1, x3

#ifdef CONFIG_ARM64_PTR_AUTH
\tptrauth_keys_init_cpu x2, x3, x4, x5
#endif

\t/* A real task/stack now exists; hand exceptions back to Linux. */
\tadr_l\tx5, vectors
\tmsr\tvbar_el1, x5
\tisb

\tbl\tsecondary_start_kernel
\tASM_BUG()
SYM_FUNC_END(__secondary_switched)
'''
    text = replace_once(text, old_switched, new_switched, "direct __secondary_switched")

    vectors = r'''

/*
 * HG680-KA stackless early-secondary exception catcher.
 * Keep it in .idmap.text so TTBR0 can service an exception before a secondary
 * stack exists. Each architectural vector slot is exactly 128 bytes.
 */
	.align	11
hg680ka_diag_vectors:
	.macro	hg680ka_diag_ventry, nr
	mov	x15, #\nr
	b	hg680ka_diag_exception
	.space	120
	.endm
	hg680ka_diag_ventry 0
	hg680ka_diag_ventry 1
	hg680ka_diag_ventry 2
	hg680ka_diag_ventry 3
	hg680ka_diag_ventry 4
	hg680ka_diag_ventry 5
	hg680ka_diag_ventry 6
	hg680ka_diag_ventry 7
	hg680ka_diag_ventry 8
	hg680ka_diag_ventry 9
	hg680ka_diag_ventry 10
	hg680ka_diag_ventry 11
	hg680ka_diag_ventry 12
	hg680ka_diag_ventry 13
	hg680ka_diag_ventry 14
	hg680ka_diag_ventry 15

hg680ka_diag_exception:
	mrs	x0, esr_el1
	mrs	x1, elr_el1
	mrs	x2, far_el1
	mrs	x3, spsr_el1
	mrs	x12, sctlr_el1
	bic	x12, x12, #SCTLR_ELx_M
	pre_disable_mmu_workaround
	msr	sctlr_el1, x12
	isb

	hg680ka_uart_marker 0x21		// !<cpu>
	mov	w4, #'V'
	hg680ka_uart_putc_reg w4
	and	w4, w15, #0xf
	cmp	w4, #9
	add	w5, w4, #'0'
	add	w4, w4, #('a' - 10)
	csel	w4, w5, w4, ls
	hg680ka_uart_putc_reg w4
	mov	w4, #' '
	hg680ka_uart_putc_reg w4
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
	hg680ka_uart_marker 0x4e		// N<cpu>: secondary_data.task was zero
997:	wfe
	b	997b
'''

    text = replace_once(
        text,
        'SYM_FUNC_END(__enable_mmu)\n',
        'SYM_FUNC_END(__enable_mmu)\n' + vectors,
        "idmap diagnostic vector table",
    )

    path.write_text(text)

    required = (
        "hg680ka_uart_marker 0x41",
        "hg680ka_uart_marker 0x45",
        "hg680ka_diag_vectors",
        "hg680ka_diag_exception",
        "hg680ka_diag_no_task",
        "hg680ka_uart_hex64 x0",
        "cbnz\tx2, 1f",
        "bl\tsecondary_start_kernel",
    )
    for needle in required:
        if needle not in text:
            raise SystemExit(f"failed to insert required diagnostic: {needle}")


def instrument_proc(path: Path) -> None:
    text = path.read_text()

    macro = r'''
/* HG680-KA temporary __cpu_setup marker; x10-x12 are scratch here. */
	.macro	hg680ka_setup_marker, ch
	movz	x10, #0xf8b0, lsl #16
1:	ldr	w12, [x10, #0x18]
	tbnz	w12, #5, 1b
	mov	w11, #\ch
	str	w11, [x10]
	mrs	x11, mpidr_el1
	and	w11, w11, #0xff
	add	w11, w11, #'0'
2:	ldr	w12, [x10, #0x18]
	tbnz	w12, #5, 2b
	str	w11, [x10]
	mov	w11, #'0' + (' ' - '0')
3:	ldr	w12, [x10, #0x18]
	tbnz	w12, #5, 3b
	str	w11, [x10]
	.endm
'''

    text = replace_once(
        text,
        '#include <asm/sysreg.h>\n',
        '#include <asm/sysreg.h>\n' + macro,
        "proc marker macro",
    )

    replacements = [
        ('SYM_FUNC_START(__cpu_setup)\n\ttlbi\tvmalle1\t\t\t\t// Invalidate local TLB\n',
         'SYM_FUNC_START(__cpu_setup)\n\thg680ka_setup_marker 0x55\n\ttlbi\tvmalle1\t\t\t\t// Invalidate local TLB\n',
         "__cpu_setup entry"),
        ('\treset_amuserenr_el0 x1\t\t\t// Disable AMU access from EL0\n\n\t/*\n\t * Default values for VMSA control registers.',
         '\treset_amuserenr_el0 x1\t\t\t// Disable AMU access from EL0\n\thg680ka_setup_marker 0x56\n\n\t/*\n\t * Default values for VMSA control registers.',
         "post basic system-register reset"),
        ('#endif\t/* CONFIG_ARM64_HW_AFDBM */\n\tmsr\tmair_el1, mair\n',
         '#endif\t/* CONFIG_ARM64_HW_AFDBM */\n\thg680ka_setup_marker 0x57\n\tmsr\tmair_el1, mair\n',
         "pre MAIR/TCR"),
        ('\tmsr\tmair_el1, mair\n\tmsr\ttcr_el1, tcr\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
         '\tmsr\tmair_el1, mair\n\tmsr\ttcr_el1, tcr\n\thg680ka_setup_marker 0x58\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
         "post MAIR/TCR"),
        ('.Lskip_indirection:\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
         '.Lskip_indirection:\n\thg680ka_setup_marker 0x59\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
         "post PIE feature setup"),
        ('\tmsr\tREG_TCR2_EL1, tcr2\n1:\n\n\t/*\n\t * Prepare SCTLR\n',
         '\tmsr\tREG_TCR2_EL1, tcr2\n1:\n\thg680ka_setup_marker 0x5a\n\n\t/*\n\t * Prepare SCTLR\n',
         "pre SCTLR value preparation"),
    ]

    for old, new, label in replacements:
        text = replace_once(text, old, new, label)

    path.write_text(text)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <arch/arm64/kernel/head.S>")

    head = Path(sys.argv[1])
    arm64 = head.parent.parent
    proc = arm64 / "mm" / "proc.S"
    if not proc.is_file():
        raise SystemExit(f"cannot find arm64 proc.S next to {head}: {proc}")

    instrument_head(head)
    instrument_proc(proc)
    print(f"instrumented {head} with HG680-KA early fault catcher/direct bring-up")
    print(f"instrumented {proc} with HG680-KA __cpu_setup markers")


if __name__ == "__main__":
    main()
