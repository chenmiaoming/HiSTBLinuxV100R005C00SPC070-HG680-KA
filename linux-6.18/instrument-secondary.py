#!/usr/bin/env python3
"""Instrument only the still-unknown high-VA arm64 secondary path on HG680-KA.

Board tests have already proved CPU1 PSCI/TF-A release, Cortex-A53 SMPEN,
init_kernel_el(), __cpu_setup(), __enable_mmu() return, and the branch/fetch into
kernel high virtual addresses.  Therefore this diagnostic deliberately leaves
secondary_startup and the complete .idmap.text path byte-for-byte upstream.

The diagnostic starts at __secondary_switched, which lives in normal .text:
  * install a 2 KiB-aligned high-VA synchronous exception vector in .text;
  * retain the normal Linux secondary initialization order;
  * record compact stage breadcrumbs in one cache-line-aligned .data block;
  * if a synchronous exception occurs before the real kernel vectors are safe,
    record ESR_EL1, ELR_EL1 and FAR_EL1 and park the secondary;
  * after init_cpu_task establishes stack/per-CPU context, restore the normal
    Linux vector table and enter secondary_start_kernel().

CPU0 prints the diagnostic block if the 5 second CPU-online wait expires.  This
avoids physical-UART code and, critically, adds nothing to arm64's one-page
.idmap.text budget.
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

    stage_macro = r'''
/* HG680-KA high-VA secondary breadcrumb.  One coherent cache line only. */
	.macro	hg680ka_diag_stage, stage
	adr_l	x12, hg680ka_diag_state
	mov	x13, #\stage
	str	x13, [x12, #32]
	dc	cvac, x12
	dsb	sy
	.endm
'''
    text = replace_once(
        text,
        '#include "efi-header.S"\n',
        '#include "efi-header.S"\n' + stage_macro,
        "diagnostic stage macro",
    )

    # Do not touch secondary_startup/.idmap.text.  The previous board run has
    # already proved the high-VA branch itself, and linker diagnostics showed
    # that placing a VBAR table in idmap is unacceptable.
    upstream_startup = (
        '\tadrp\tx1, swapper_pg_dir\n'
        '\tadrp\tx2, idmap_pg_dir\n'
        '\tbl\t__enable_mmu\n'
        '\tldr\tx8, =__secondary_switched\n'
        '\tbr\tx8\n'
    )
    if text.count(upstream_startup) != 1:
        raise SystemExit("secondary_startup is not the expected untouched upstream sequence")

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
\t/* J1 already proved that this high-VA entry is executable.  From here on,
\t * keep Linux's normal semantics and only add diagnostics. */
\tldr\tx17, =hg680ka_diag_vectors
\tmsr\tvbar_el1, x17
\tisb
\thg680ka_diag_stage 0x70

\tmov\tx0, x20
\thg680ka_diag_stage 0x71
\tbl\tset_cpu_boot_mode_flag
\thg680ka_diag_stage 0x72

\tmov\tx0, x20
\thg680ka_diag_stage 0x73
\tbl\tfinalise_el2
\thg680ka_diag_stage 0x74

\tstr_l\txzr, __early_cpu_boot_status, x3
\thg680ka_diag_stage 0x75

\tadr_l\tx0, secondary_data
\thg680ka_diag_stage 0x76
\tldr\tx2, [x0, #CPU_BOOT_TASK]
\tcbz\tx2, __secondary_too_slow
\thg680ka_diag_stage 0x77

\tinit_cpu_task x2, x1, x3
\thg680ka_diag_stage 0x78

#ifdef CONFIG_ARM64_PTR_AUTH
\tptrauth_keys_init_cpu x2, x3, x4, x5
#endif

\t/* Stack and per-CPU context now exist; hand exceptions back to Linux. */
\tadr_l\tx5, vectors
\tmsr\tvbar_el1, x5
\tisb
\thg680ka_diag_stage 0x79

\tbl\tsecondary_start_kernel
\tASM_BUG()
SYM_FUNC_END(__secondary_switched)
'''
    text = replace_once(text, old_switched, new_switched, "instrument __secondary_switched")

    catcher = r'''

/*
 * HG680-KA early high-VA synchronous catcher.  This is ordinary .text, not
 * .idmap.text.  Only Current EL with SPx synchronous (+0x200) is populated;
 * asynchronous exceptions remain masked on this path.
 */
	.align	11
	.global	hg680ka_diag_vectors
hg680ka_diag_vectors:
	.space	0x200
	b	hg680ka_diag_exception

	.global	hg680ka_diag_exception
hg680ka_diag_exception:
	mrs	x0, esr_el1
	mrs	x1, elr_el1
	mrs	x2, far_el1
	adr_l	x3, hg680ka_diag_state
	stp	x0, x1, [x3]
	str	x2, [x3, #16]
	mov	x4, #0xe1
	str	x4, [x3, #24]
	dc	cvac, x3
	dsb	sy
996:	wfe
	b	996b

	.pushsection .data
	.balign	64
	.global	hg680ka_diag_state
hg680ka_diag_state:
	.quad	0		// +0  ESR_EL1
	.quad	0		// +8  ELR_EL1
	.quad	0		// +16 FAR_EL1
	.quad	0		// +24 event (0xe1 == synchronous exception)
	.quad	0		// +32 last completed/entered stage
	.quad	0
	.quad	0
	.quad	0
	.popsection
'''

    # __secondary_too_slow is in normal .text, so the aligned catcher remains
    # completely outside the identity-mapped section.
    text = replace_once(
        text,
        'SYM_FUNC_END(__secondary_too_slow)',
        'SYM_FUNC_END(__secondary_too_slow)' + catcher,
        "high-VA catcher/state",
    )

    path.write_text(text)

    required = (
        "hg680ka_diag_vectors",
        "hg680ka_diag_exception",
        "hg680ka_diag_state",
        "hg680ka_diag_stage 0x70",
        "hg680ka_diag_stage 0x79",
        "bl\tset_cpu_boot_mode_flag",
        "bl\tfinalise_el2",
        "bl\tsecondary_start_kernel",
    )
    for needle in required:
        if needle not in text:
            raise SystemExit(f"failed to insert required diagnostic: {needle}")

    for obsolete in ("hg680ka_uart_marker", "hg680ka_uart_putc_reg",
                     "hg680ka_diag_no_task"):
        if obsolete in text:
            raise SystemExit(f"obsolete idmap/UART diagnostic unexpectedly present: {obsolete}")


def instrument_smp(path: Path) -> None:
    text = path.read_text()

    text = replace_once(
        text,
        'struct secondary_data secondary_data;\n',
        'struct secondary_data secondary_data;\n'
        'extern u64 hg680ka_diag_state[8];\n',
        "smp diagnostic extern",
    )

    old = '\tpr_crit("CPU%u: failed to come online\\n", cpu);\n'
    new = '''\tpr_crit("CPU%u: failed to come online\\n", cpu);
\tpr_crit("CPU%u: HG680-KA stage=0x%llx event=0x%llx ESR=0x%016llx ELR=0x%016llx FAR=0x%016llx\\n",
\t\tcpu,
\t\t(unsigned long long)READ_ONCE(hg680ka_diag_state[4]),
\t\t(unsigned long long)READ_ONCE(hg680ka_diag_state[3]),
\t\t(unsigned long long)READ_ONCE(hg680ka_diag_state[0]),
\t\t(unsigned long long)READ_ONCE(hg680ka_diag_state[1]),
\t\t(unsigned long long)READ_ONCE(hg680ka_diag_state[2]));
'''
    text = replace_once(text, old, new, "CPU-online timeout diagnostic")
    path.write_text(text)

    if "HG680-KA stage=0x%llx" not in text:
        raise SystemExit("failed to instrument smp.c timeout")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            f"usage: {sys.argv[0]} <arch/arm64/kernel/head.S> <arch/arm64/kernel/smp.c>"
        )

    head = Path(sys.argv[1])
    smp = Path(sys.argv[2])
    instrument_head(head)
    instrument_smp(smp)
    print(f"instrumented {head} and {smp} with high-VA HG680-KA diagnostics")


if __name__ == "__main__":
    main()
