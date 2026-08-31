#!/usr/bin/env python3
"""Inject temporary HG680-KA secondary-CPU diagnostics into Linux arm64.

This is intentionally a bring-up-only transformation. Every anchor must match
exactly once so a kernel source change cannot silently instrument the wrong
place.

Before the MMU is enabled, PL011 marker writes poll UARTFR.TXFF before every
UARTDR access. Once stage-1 translation is enabled, the physical PL011 address
is not guaranteed to be mapped, so post-MMU progress is recorded in a dedicated
cache-line-aligned kernel data breadcrumb instead. The secondary cleans each
breadcrumb write to PoC; CPU0 prints the last observed stage if bring-up times
out.

The previous one-shot MMU round-trip test reached M1 on CPU1. That proves the
secondary completed set_sctlr_el1(), including the following ISB/I-cache/TLB
synchronization sequence, and could execute again after disabling translation.
This revision therefore removes the deliberate secondary park and traces the
normal path from __enable_mmu() through __secondary_switched and into
secondary_start_kernel().
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
/* HG680-KA temporary secondary CPU bring-up marker.
 * Poll PL011 UARTFR.TXFF (bit 5) before every UARTDR write. */
	.macro	hg680ka_uart_marker, ch
	movz	x9, #0xf8b0, lsl #16
1:	ldr	w11, [x9, #0x18]
	tbnz	w11, #5, 1b
	mov	w10, #\ch
	str	w10, [x9]
	mrs	x10, mpidr_el1
	and	w10, w10, #0xff
	add	w10, w10, #'0'
2:	ldr	w11, [x9, #0x18]
	tbnz	w11, #5, 2b
	str	w10, [x9]
	mov	w10, #' '
3:	ldr	w11, [x9, #0x18]
	tbnz	w11, #5, 3b
	str	w10, [x9]
	.endm

/* Post-MMU progress cannot safely use the physical UART because MMIO is not
 * guaranteed to be mapped yet. Record a stage in normal kernel memory and
 * clean the line to PoC so CPU0 can report it after a bring-up timeout. */
	.macro	hg680ka_stage, stage
	ldr	x12, =hg680ka_secondary_stage
	mov	w13, #\stage
	str	w13, [x12]
	dc	cvac, x12
	dsb	sy
	.endm
'''

    text = replace_once(text, '#include "efi-header.S"\n', '#include "efi-header.S"\n' + macros, "head diagnostic macros")
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
\thg680ka_stage 0x61
\tldr\tx8, =__secondary_switched
\thg680ka_stage 0x62
\tbr\tx8
''',
        "post MMU secondary path",
    )
    text = replace_once(
        text,
        'SYM_FUNC_START_LOCAL(__secondary_switched)\n\tmov\tx0, x20\n\tbl\tset_cpu_boot_mode_flag\n\n\tmov\tx0, x20\n\tbl\tfinalise_el2\n\n\tstr_l\txzr, __early_cpu_boot_status, x3\n\tadr_l\tx5, vectors\n\tmsr\tvbar_el1, x5\n\tisb\n\n\tadr_l\tx0, secondary_data\n\tldr\tx2, [x0, #CPU_BOOT_TASK]\n\tcbz\tx2, __secondary_too_slow\n\n\tinit_cpu_task x2, x1, x3\n',
        '''SYM_FUNC_START_LOCAL(__secondary_switched)
\thg680ka_stage 0x70
\tmov\tx0, x20
\tbl\tset_cpu_boot_mode_flag
\thg680ka_stage 0x71

\tmov\tx0, x20
\tbl\tfinalise_el2
\thg680ka_stage 0x72

\tstr_l\txzr, __early_cpu_boot_status, x3
\thg680ka_stage 0x73
\tadr_l\tx5, vectors
\tmsr\tvbar_el1, x5
\tisb
\thg680ka_stage 0x74

\tadr_l\tx0, secondary_data
\tldr\tx2, [x0, #CPU_BOOT_TASK]
\thg680ka_stage 0x75
\tcbz\tx2, __secondary_too_slow

\tinit_cpu_task x2, x1, x3
\thg680ka_stage 0x76
''',
        "secondary switched stages",
    )
    text = replace_once(
        text,
        '\tbl\tsecondary_start_kernel\n\tASM_BUG()\nSYM_FUNC_END(__secondary_switched)\n',
        '\thg680ka_stage 0x77\n\tbl\tsecondary_start_kernel\n\tASM_BUG()\nSYM_FUNC_END(__secondary_switched)\n',
        "secondary_start_kernel stage",
    )
    text = replace_once(
        text,
        'SYM_FUNC_END(__secondary_too_slow)\n',
        '''SYM_FUNC_END(__secondary_too_slow)

/* HG680-KA post-MMU secondary progress breadcrumb. Keep it isolated on its
 * own cache line so unrelated boot-CPU data does not create false sharing. */
\t.pushsection .data
\t.balign 64
\t.global hg680ka_secondary_stage
hg680ka_secondary_stage:
\t.quad 0
\t.space 56
\t.popsection
''',
        "secondary stage storage",
    )
    path.write_text(text)

    for marker in ("0x41", "0x42", "0x43", "0x50", "0x44", "0x45"):
        if f"hg680ka_uart_marker {marker}" not in text:
            raise SystemExit(f"failed to insert head marker {marker}")
    for stage in ("0x61", "0x62", "0x70", "0x71", "0x72", "0x73", "0x74", "0x75", "0x76", "0x77"):
        if f"hg680ka_stage {stage}" not in text:
            raise SystemExit(f"failed to insert post-MMU stage {stage}")


def instrument_proc(path: Path) -> None:
    text = path.read_text()

    # __cpu_setup uses x15/x16/x17 for TCR/MAIR and explicit x1/x5/x6/x9
    # temporaries. x10-x12 are not live here, so reserve them for the marker.
    macro = r'''
/* HG680-KA temporary __cpu_setup marker; x10-x12 are scratch here.
 * Poll PL011 UARTFR.TXFF (bit 5) before every UARTDR write. */
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
	mov	w11, #' '
3:	ldr	w12, [x10, #0x18]
	tbnz	w12, #5, 3b
	str	w11, [x10]
	.endm
'''

    text = replace_once(text, '#include <asm/sysreg.h>\n', '#include <asm/sysreg.h>\n' + macro, "proc marker macro")
    text = replace_once(
        text,
        'SYM_FUNC_START(__cpu_setup)\n\ttlbi\tvmalle1\t\t\t\t// Invalidate local TLB\n',
        'SYM_FUNC_START(__cpu_setup)\n\thg680ka_setup_marker 0x55\n\ttlbi\tvmalle1\t\t\t\t// Invalidate local TLB\n',
        "__cpu_setup entry",
    )
    text = replace_once(
        text,
        '\treset_amuserenr_el0 x1\t\t\t// Disable AMU access from EL0\n\n\t/*\n\t * Default values for VMSA control registers.',
        '\treset_amuserenr_el0 x1\t\t\t// Disable AMU access from EL0\n\thg680ka_setup_marker 0x56\n\n\t/*\n\t * Default values for VMSA control registers.',
        "post basic system-register reset",
    )
    text = replace_once(
        text,
        '#endif\t/* CONFIG_ARM64_HW_AFDBM */\n\tmsr\tmair_el1, mair\n',
        '#endif\t/* CONFIG_ARM64_HW_AFDBM */\n\thg680ka_setup_marker 0x57\n\tmsr\tmair_el1, mair\n',
        "pre MAIR/TCR",
    )
    text = replace_once(
        text,
        '\tmsr\tmair_el1, mair\n\tmsr\ttcr_el1, tcr\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
        '\tmsr\tmair_el1, mair\n\tmsr\ttcr_el1, tcr\n\thg680ka_setup_marker 0x58\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
        "post MAIR/TCR",
    )
    text = replace_once(
        text,
        '.Lskip_indirection:\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
        '.Lskip_indirection:\n\thg680ka_setup_marker 0x59\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
        "post PIE feature setup",
    )
    text = replace_once(
        text,
        '\tmsr\tREG_TCR2_EL1, tcr2\n1:\n\n\t/*\n\t * Prepare SCTLR\n',
        '\tmsr\tREG_TCR2_EL1, tcr2\n1:\n\thg680ka_setup_marker 0x5a\n\n\t/*\n\t * Prepare SCTLR\n',
        "pre SCTLR value preparation",
    )
    path.write_text(text)

    for marker in ("0x55", "0x56", "0x57", "0x58", "0x59", "0x5a"):
        if f"hg680ka_setup_marker {marker}" not in text:
            raise SystemExit(f"failed to insert __cpu_setup marker {marker}")


def instrument_smp(path: Path) -> None:
    text = path.read_text()

    text = replace_once(
        text,
        'struct secondary_data secondary_data;\n',
        'struct secondary_data secondary_data;\nextern u64 hg680ka_secondary_stage;\n',
        "secondary stage extern",
    )
    text = replace_once(
        text,
        '\tpr_crit("CPU%u: failed to come online\\n", cpu);\n',
        '\tpr_crit("CPU%u: failed to come online; HG680-KA secondary stage=0x%llx\\n",\\n\t\tcpu, (unsigned long long)READ_ONCE(hg680ka_secondary_stage));\n',
        "secondary timeout stage report",
    )
    path.write_text(text)

    if "HG680-KA secondary stage=0x%llx" not in text:
        raise SystemExit("failed to insert secondary timeout stage report")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <arch/arm64/kernel/head.S>")

    head = Path(sys.argv[1])
    arm64 = head.parent.parent
    proc = arm64 / "mm" / "proc.S"
    smp = arm64 / "kernel" / "smp.c"
    if not proc.is_file():
        raise SystemExit(f"cannot find arm64 proc.S next to {head}: {proc}")
    if not smp.is_file():
        raise SystemExit(f"cannot find arm64 smp.c next to {head}: {smp}")

    instrument_head(head)
    instrument_proc(proc)
    instrument_smp(smp)
    print(f"instrumented {head} with FIFO-safe HG680-KA secondary markers A-E/P")
    print(f"instrumented {proc} with FIFO-safe HG680-KA __cpu_setup markers U-Z")
    print(f"instrumented {smp} with post-MMU secondary breadcrumb reporting")


if __name__ == "__main__":
    main()
