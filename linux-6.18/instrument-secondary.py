#!/usr/bin/env python3
# Inject temporary HG680-KA secondary-CPU diagnostics into Linux arm64.

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
/* HG680-KA pre-MMU UART marker. */
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

/* HG680-KA post-MMU progress breadcrumb. */
	.macro	hg680ka_stage, stage
	ldr	x12, =hg680ka_secondary_stage
	mov	w13, #\stage
	str	w13, [x12]
	dc	cvac, x12
	dsb	sy
	.endm
'''

    text = replace_once(text, '#include "efi-header.S"\n',
                        '#include "efi-header.S"\n' + macros,
                        "head diagnostic macros")

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
        '\tadrp\tx2, idmap_pg_dir\n\thg680ka_uart_marker 0x45\n\tbl\t__enable_mmu\n\thg680ka_stage 0x61\n\tldr\tx8, =__secondary_switched\n\thg680ka_stage 0x62\n\tbr\tx8\n',
        "post MMU secondary path",
    )

    text = replace_once(
        text,
        'SYM_FUNC_START_LOCAL(__secondary_switched)\n\tmov\tx0, x20\n\tbl\tset_cpu_boot_mode_flag\n\n\tmov\tx0, x20\n\tbl\tfinalise_el2\n\n\tstr_l\txzr, __early_cpu_boot_status, x3\n\tadr_l\tx5, vectors\n\tmsr\tvbar_el1, x5\n\tisb\n\n\tadr_l\tx0, secondary_data\n\tldr\tx2, [x0, #CPU_BOOT_TASK]\n\tcbz\tx2, __secondary_too_slow\n\n\tinit_cpu_task x2, x1, x3\n',
        'SYM_FUNC_START_LOCAL(__secondary_switched)\n\thg680ka_stage 0x70\n\tmov\tx0, x20\n\tbl\tset_cpu_boot_mode_flag\n\thg680ka_stage 0x71\n\n\tmov\tx0, x20\n\tbl\tfinalise_el2\n\thg680ka_stage 0x72\n\n\tstr_l\txzr, __early_cpu_boot_status, x3\n\thg680ka_stage 0x73\n\tadr_l\tx5, vectors\n\tmsr\tvbar_el1, x5\n\tisb\n\thg680ka_stage 0x74\n\n\tadr_l\tx0, secondary_data\n\tldr\tx2, [x0, #CPU_BOOT_TASK]\n\thg680ka_stage 0x75\n\tcbz\tx2, __secondary_too_slow\n\n\tinit_cpu_task x2, x1, x3\n\thg680ka_stage 0x76\n',
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

/* HG680-KA post-MMU secondary progress breadcrumb, isolated on a cache line. */
	.pushsection .data
	.balign 64
	.global hg680ka_secondary_stage
hg680ka_secondary_stage:
	.quad 0
	.space 56
	.popsection
''',
        "secondary stage storage",
    )

    path.write_text(text)

    for marker in ("0x41", "0x42", "0x43", "0x50", "0x44", "0x45"):
        if f"hg680ka_uart_marker {marker}" not in text:
            raise SystemExit(f"failed to insert head marker {marker}")
    for stage in ("0x61", "0x62", "0x70", "0x71", "0x72",
                  "0x73", "0x74", "0x75", "0x76", "0x77"):
        if f"hg680ka_stage {stage}" not in text:
            raise SystemExit(f"failed to insert post-MMU stage {stage}")


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
	mov	w11, #' '
3:	ldr	w12, [x10, #0x18]
	tbnz	w12, #5, 3b
	str	w11, [x10]
	.endm
'''

    text = replace_once(text, '#include <asm/sysreg.h>\n',
                        '#include <asm/sysreg.h>\n' + macro,
                        "proc marker macro")

    replacements = [
        (
            'SYM_FUNC_START(__cpu_setup)\n\ttlbi\tvmalle1\t\t\t\t// Invalidate local TLB\n',
            'SYM_FUNC_START(__cpu_setup)\n\thg680ka_setup_marker 0x55\n\ttlbi\tvmalle1\t\t\t\t// Invalidate local TLB\n',
            "__cpu_setup entry",
        ),
        (
            '\treset_amuserenr_el0 x1\t\t\t// Disable AMU access from EL0\n\n\t/*\n\t * Default values for VMSA control registers.',
            '\treset_amuserenr_el0 x1\t\t\t// Disable AMU access from EL0\n\thg680ka_setup_marker 0x56\n\n\t/*\n\t * Default values for VMSA control registers.',
            "post basic system-register reset",
        ),
        (
            '#endif\t/* CONFIG_ARM64_HW_AFDBM */\n\tmsr\tmair_el1, mair\n',
            '#endif\t/* CONFIG_ARM64_HW_AFDBM */\n\thg680ka_setup_marker 0x57\n\tmsr\tmair_el1, mair\n',
            "pre MAIR/TCR",
        ),
        (
            '\tmsr\tmair_el1, mair\n\tmsr\ttcr_el1, tcr\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
            '\tmsr\tmair_el1, mair\n\tmsr\ttcr_el1, tcr\n\thg680ka_setup_marker 0x58\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
            "post MAIR/TCR",
        ),
        (
            '.Lskip_indirection:\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
            '.Lskip_indirection:\n\thg680ka_setup_marker 0x59\n\n\tmrs_s\tx1, SYS_ID_AA64MMFR3_EL1\n',
            "post PIE feature setup",
        ),
        (
            '\tmsr\tREG_TCR2_EL1, tcr2\n1:\n\n\t/*\n\t * Prepare SCTLR\n',
            '\tmsr\tREG_TCR2_EL1, tcr2\n1:\n\thg680ka_setup_marker 0x5a\n\n\t/*\n\t * Prepare SCTLR\n',
            "pre SCTLR value preparation",
        ),
    ]

    for old, new, label in replacements:
        text = replace_once(text, old, new, label)

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
        '\tpr_crit("CPU%u: failed to come online; HG680-KA secondary stage=0x%llx\\n", cpu, (unsigned long long)READ_ONCE(hg680ka_secondary_stage));\n',
        "secondary timeout stage report",
    )

    path.write_text(text)


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

    print(f"instrumented {head} with HG680-KA pre-MMU markers and post-MMU stages")
    print(f"instrumented {proc} with HG680-KA __cpu_setup markers")
    print(f"instrumented {smp} with HG680-KA secondary timeout stage reporting")


if __name__ == "__main__":
    main()
