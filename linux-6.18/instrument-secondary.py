#!/usr/bin/env python3
"""Apply HG680-KA arm64 secondary-CPU bring-up instrumentation and cache fix.

HiSilicon's original 32-bit Hi3798MV310 BSP does more than set Cortex-A53
CPUECTLR.SMPEN before entering Linux on a secondary CPU.  Its platform
headsmp.S calls flash_cache_all(), which in turn calls v7_invalidate_l1()
while the secondary's data cache is disabled.  The BSP comment explains why:
the secondary L1 can come out of reset with undefined tags/data, so a later
clean+invalidate can write garbage to memory; the L1 must first be invalidated
without cleaning.

Our arm64 PSCI path already proves SMPEN=1, __cpu_setup(), __enable_mmu(), the
return from __enable_mmu(), and a TTBR1 high-VA instruction fetch all work.
The remaining failure begins when the normal high-VA path starts touching
cacheable kernel data, and an earlier dc cvac + dsb diagnostic could stall the
whole machine.  This revision therefore ports the BSP's missing secondary-L1
reset requirement to arm64: immediately after __cpu_setup(), while SCTLR.C/M
are still off and before any Linux cacheable data access on the secondary,
invalidate the L1 data/unified cache by set/way.  Then follow the completely
normal Linux secondary path; no deliberate post-MMU park remains.

The pre-MMU UART markers are retained because they do not require a mapping and
have already been shown not to perturb the path.  They poll PL011 TXFF before
every character.
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
/* HG680-KA pre-MMU UART marker. Poll PL011 UARTFR.TXFF before each write. */
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

/*
 * HG680-KA / Hi3798MV310 secondary L1 reset.
 *
 * The vendor ARMv7 BSP performs an invalidate-only of L1 before generic
 * secondary startup because an A53 secondary can expose undefined L1 state
 * after reset.  Do the AArch64 equivalent while SCTLR_EL1.C and M are still
 * clear.  CCSIDR_EL1 on this ARMv8.0 Cortex-A53 uses the architectural
 * pre-CCIDX layout: LineSize[2:0], Associativity[12:3], NumSets[27:13].
 *
 * The DC ISW Way field is defined in the low 32-bit Set/Way encoding, so the
 * way shift must be CLZ32(NumWays - 1), matching the vendor ARMv7 routine.
 * Using CLZ64 would place the Way field in bits 63:32 and invalidate the wrong
 * set/way operands.
 *
 * x0 is deliberately preserved: __cpu_setup() returns the SCTLR value for
 * __enable_mmu() in x0.  x20 is also preserved (boot mode).  x3-x10 are
 * scratch at this point in secondary_startup.
 */
	.macro	hg680ka_invalidate_l1_dcache
	dsb	sy
	mov	x3, xzr			// L1 data/unified cache, InD=0 Level=0
	msr	csselr_el1, x3
	isb
	mrs	x3, ccsidr_el1

	and	x4, x3, #0x7		// log2(bytes/line) - 4
	add	x4, x4, #4		// set field shift
	ubfx	x5, x3, #3, #10	// NumWays - 1
	clz	w6, w5			// 32-bit Way field shift (e.g. 4 ways -> 30)
	ubfx	x7, x3, #13, #15	// NumSets - 1

1:	mov	x8, x5
2:	lsl	x9, x8, x6
	lsl	x10, x7, x4
	orr	x9, x9, x10		// level bits [3:1] are zero for L1
	dc	isw, x9
	subs	x8, x8, #1
	b.pl	2b
	subs	x7, x7, #1
	b.pl	1b
	dsb	sy
	isb
	.endm
'''

    text = replace_once(
        text,
        '#include "efi-header.S"\n',
        '#include "efi-header.S"\n' + macros,
        "head diagnostic/cache macros",
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
        '''\thg680ka_uart_marker 0x50
\tbl\t__cpu_setup\t\t\t// initialise processor
\thg680ka_uart_marker 0x44

\t/* Match the Hi3798MV310 vendor BSP's secondary L1 invalidate before
\t * caches are enabled. x0 (prepared SCTLR) must survive this macro. */
\thg680ka_invalidate_l1_dcache

\tadrp\tx1, swapper_pg_dir
''',
        "secondary L1 reset after __cpu_setup",
    )

    text = replace_once(
        text,
        '\tadrp\tx2, idmap_pg_dir\n\tbl\t__enable_mmu\n\tldr\tx8, =__secondary_switched\n\tbr\tx8\n',
        '''\tadrp\tx2, idmap_pg_dir
\thg680ka_uart_marker 0x45
\tbl\t__enable_mmu
\tldr\tx8, =__secondary_switched
\tbr\tx8
''',
        "normal post-MMU secondary path",
    )

    path.write_text(text)

    for marker in ("0x41", "0x42", "0x43", "0x50", "0x44", "0x45"):
        if f"hg680ka_uart_marker {marker}" not in text:
            raise SystemExit(f"failed to insert head marker {marker}")
    if "hg680ka_invalidate_l1_dcache" not in text or "dc\tisw" not in text:
        raise SystemExit("failed to insert HG680-KA secondary L1 invalidate")
    if "clz\tw6, w5" not in text:
        raise SystemExit("secondary L1 invalidate must use 32-bit CLZ for WayShift")


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

    text = replace_once(
        text,
        '#include <asm/sysreg.h>\n',
        '#include <asm/sysreg.h>\n' + macro,
        "proc marker macro",
    )

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

    print(f"instrumented {head} with HG680-KA vendor-style secondary L1 invalidate")
    print(f"instrumented {proc} with HG680-KA __cpu_setup markers")


if __name__ == "__main__":
    main()
