#!/usr/bin/env python3
"""Inject temporary HG680-KA secondary-CPU UART markers into Linux arm64.

This is intentionally a bring-up-only transformation. Every anchor must match
exactly once so a kernel source change cannot silently instrument the wrong
place.

PL011 marker writes poll UARTFR.TXFF before every UARTDR access. Without this,
back-to-back early markers can fill the small TX FIFO and perturb the exact
secondary path being measured.

The final M marker is a deliberate one-shot MMU round-trip diagnostic. After
set_sctlr_el1() returns with the MMU enabled, execution is still in .idmap.text.
The instrumentation immediately clears SCTLR_EL1.M using the kernel's normal
pre-disable workaround, emits M<cpu> through the physical UART, and parks that
secondary. Seeing M therefore proves that the MMU-enable sequence itself
completed; absence of M narrows the stall to the SCTLR/MMU-enable boundary.
The test intentionally never onlines the secondary.
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
'''

    text = replace_once(text, '#include "efi-header.S"\n', '#include "efi-header.S"\n' + macro, "head marker macro")
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
        '\tload_ttbr1 x1, x1, x3\n\n\tset_sctlr_el1\tx0\n',
        '''\tload_ttbr1 x1, x1, x3\n\n\thg680ka_uart_marker 0x45\n\tset_sctlr_el1\tx0\n\n\t/* HG680-KA one-shot MMU round-trip diagnostic. We are still executing\n\t * from .idmap.text here. If set_sctlr_el1() completed, switch M back\n\t * off using the same pre-disable workaround used by normal arm64 code,\n\t * then touch the physical PL011, emit M<cpu>, and park. This intentionally\n\t * prevents the secondary from reaching normal C code. */\n\tmrs\tx12, sctlr_el1\n\tbic\tx12, x12, #SCTLR_ELx_M\n\tpre_disable_mmu_workaround\n\tmsr\tsctlr_el1, x12\n\tisb\n\thg680ka_uart_marker 0x4d\n998:\twfe\n\tb\t998b\n''',
        "post SCTLR_EL1 MMU round-trip",
    )
    path.write_text(text)

    for marker in ("0x41", "0x42", "0x43", "0x50", "0x44", "0x45", "0x4d"):
        if f"hg680ka_uart_marker {marker}" not in text:
            raise SystemExit(f"failed to insert head marker {marker}")


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
    print(f"instrumented {head} with FIFO-safe HG680-KA secondary markers A-E/P/M")
    print(f"instrumented {proc} with FIFO-safe HG680-KA __cpu_setup markers U-Z")


if __name__ == "__main__":
    main()
