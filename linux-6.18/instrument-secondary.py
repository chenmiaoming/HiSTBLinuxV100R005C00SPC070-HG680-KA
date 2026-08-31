#!/usr/bin/env python3
"""Inject temporary HG680-KA secondary-CPU diagnostics into Linux arm64.

This revision is a high-VA instruction-fetch probe. The previous R1 test proved
CPU1 can enable stage-1 translation in __enable_mmu(), return normally to the
identity-mapped secondary_startup continuation, disable translation again, and
continue executing.

To isolate TTBR1/kernel-VA instruction fetch from every data-memory access, this
probe keeps the MMU enabled after __enable_mmu(), loads the address of a tiny
trampoline placed in normal .text, and branches to it. The trampoline performs
only `br x9`, where x9 already contains an identity-mapped continuation address.
Back in .idmap.text the probe disables the MMU, prints J<cpu> via the physical
PL011, and parks. Seeing J1 proves CPU1 can fetch and execute normal high-VA
kernel text through TTBR1 and return to the idmap without touching kernel data.
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

    macro = r'''
/* HG680-KA pre-MMU / MMU-off UART marker. Poll PL011 TXFF. */
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
'''

    text = replace_once(text, '#include "efi-header.S"\n',
                        '#include "efi-header.S"\n' + macro,
                        "head diagnostic macro")

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

\t/* High-VA instruction-fetch probe. x9 is prepared while executing from
\t * the identity map and remains a low VA valid through TTBR0. The target
\t * trampoline lives in normal .text and executes only `br x9`, so no
\t * post-MMU data access is introduced by the diagnostic itself. */
\tadr\tx9, 997f
\tldr\tx8, =hg680ka_highva_probe
\tbr\tx8
997:
\t/* Reaching this label proves the high-VA trampoline executed. Disable
\t * translation before touching the physical PL011. */
\tmrs\tx12, sctlr_el1
\tbic\tx12, x12, #SCTLR_ELx_M
\tpre_disable_mmu_workaround
\tmsr\tsctlr_el1, x12
\tisb
\thg680ka_uart_marker 0x4a
998:\twfe
\tb\t998b
''',
        "high-VA instruction-fetch probe",
    )

    text = replace_once(
        text,
        '\t.text\nSYM_FUNC_START_LOCAL(__secondary_switched)\n',
        '''\t.text
/* HG680-KA high-VA instruction-fetch trampoline. It deliberately performs no
 * memory access; x9 contains an identity-mapped continuation address. */
SYM_FUNC_START_LOCAL(hg680ka_highva_probe)
\tbr\tx9
SYM_FUNC_END(hg680ka_highva_probe)

SYM_FUNC_START_LOCAL(__secondary_switched)
''',
        "high-VA trampoline",
    )

    path.write_text(text)

    for marker in ("0x41", "0x42", "0x43", "0x50", "0x44", "0x45", "0x4a"):
        if f"hg680ka_uart_marker {marker}" not in text:
            raise SystemExit(f"failed to insert head marker {marker}")
    if "SYM_FUNC_START_LOCAL(hg680ka_highva_probe)" not in text:
        raise SystemExit("failed to insert high-VA trampoline")


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

    for marker in ("0x55", "0x56", "0x57", "0x58", "0x59", "0x5a"):
        if f"hg680ka_setup_marker {marker}" not in text:
            raise SystemExit(f"failed to insert __cpu_setup marker {marker}")


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

    print(f"instrumented {head} with HG680-KA high-VA instruction-fetch probe J")
    print(f"instrumented {proc} with HG680-KA __cpu_setup markers U-Z")


if __name__ == "__main__":
    main()
