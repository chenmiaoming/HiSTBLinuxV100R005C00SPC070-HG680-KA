#!/usr/bin/env python3
"""Pure control-flow proof for the first high-VA arm64 secondary fetch on HG680-KA.

Board tests already proved CPU1 PSCI/TF-A release, Cortex-A53 SMPEN,
init_kernel_el(), __cpu_setup(), and that __enable_mmu() can enable stage-1 and
return while the CPU is still executing through the identity mapping.

A previous high-VA breadcrumb test was invalid because its very first probe did
a normal-RAM store followed by DC CVAC + DSB SY; the board then became globally
silent, so the diagnostic itself may have caused the stall.

This probe therefore performs no high-VA data access and no cache maintenance:
  * after __enable_mmu() returns in .idmap.text, x19 is loaded with the runtime
    physical address of a tiny identity-mapped return helper;
  * Linux branches normally to the high-VA __secondary_switched symbol;
  * the first body instruction there is only `br x19` (after the normal BTI);
  * back in the idmap helper, MMU is disabled, physical PL011 prints J<cpu>, and
    the secondary parks.

Seeing J1 proves TTBR1 high-VA instruction fetch and the branch into
__secondary_switched without relying on coherent RAM, VBAR, exceptions, or
high-VA MMIO. The helper is intentionally tiny and remains well within arm64's
single-page .idmap.text limit.
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

    upstream_startup = (
        '\tadrp\tx1, swapper_pg_dir\n'
        '\tadrp\tx2, idmap_pg_dir\n'
        '\tbl\t__enable_mmu\n'
        '\tldr\tx8, =__secondary_switched\n'
        '\tbr\tx8\n'
    )
    probed_startup = (
        '\tadrp\tx1, swapper_pg_dir\n'
        '\tadrp\tx2, idmap_pg_dir\n'
        '\tbl\t__enable_mmu\n'
        '\t/* x19 is computed through the identity alias, so ADR yields the\n'
        '\t * physical runtime address of the helper even with the MMU on. */\n'
        '\tadr\tx19, hg680ka_highva_return\n'
        '\tldr\tx8, =__secondary_switched\n'
        '\tbr\tx8\n'
    )
    text = replace_once(text, upstream_startup, probed_startup, "secondary high-VA branch probe")

    # SYM_FUNC_START_LOCAL emits the architecture's normal function-entry BTI
    # when enabled. The only injected high-VA body instruction is BR X19.
    old_switched = 'SYM_FUNC_START_LOCAL(__secondary_switched)\n\tmov\tx0, x20\n'
    new_switched = (
        'SYM_FUNC_START_LOCAL(__secondary_switched)\n'
        '\t/* HG680-KA: pure high-VA instruction-fetch proof. No data access. */\n'
        '\tbr\tx19\n'
        '\tmov\tx0, x20\n'
    )
    text = replace_once(text, old_switched, new_switched, "high-VA return branch")

    helper = r'''

/*
 * HG680-KA identity-mapped return helper. Entry is with MMU on through TTBR0;
 * after SCTLR.M is cleared, execution continues at the same physical address.
 */
SYM_CODE_START_LOCAL(hg680ka_highva_return)
	mrs	x12, sctlr_el1
	bic	x12, x12, #SCTLR_ELx_M
	pre_disable_mmu_workaround
	msr	sctlr_el1, x12
	isb

	/* PL011 UART0 physical base 0xf8b00000. Print J<Aff0> and park. */
	movz	x9, #0xf8b0, lsl #16
1:	ldr	w11, [x9, #0x18]
	tbnz	w11, #5, 1b
	mov	w10, #'J'
	str	w10, [x9]
2:	ldr	w11, [x9, #0x18]
	tbnz	w11, #5, 2b
	mrs	x10, mpidr_el1
	and	w10, w10, #0xff
	add	w10, w10, #'0'
	str	w10, [x9]
3:	ldr	w11, [x9, #0x18]
	tbnz	w11, #5, 3b
	mov	w10, #' '
	str	w10, [x9]
4:	wfe
	b	4b
SYM_CODE_END(hg680ka_highva_return)
'''

    # Still in .idmap.text here; .text follows immediately afterwards.
    text = replace_once(
        text,
        'SYM_FUNC_END(secondary_startup)\n\n\t.text\n',
        'SYM_FUNC_END(secondary_startup)' + helper + '\n\t.text\n',
        "identity-mapped J return helper",
    )

    path.write_text(text)

    required = (
        "adr\tx19, hg680ka_highva_return",
        "br\tx19",
        "SYM_CODE_START_LOCAL(hg680ka_highva_return)",
        "mov\tw10, #'J'",
        "bic\tx12, x12, #SCTLR_ELx_M",
    )
    for needle in required:
        if needle not in text:
            raise SystemExit(f"failed to insert required diagnostic: {needle}")

    # Do not regress to intrusive post-MMU diagnostics.
    for forbidden in (
        "hg680ka_diag_stage",
        "hg680ka_diag_state",
        "hg680ka_diag_vectors",
        "hg680ka_diag_exception",
        "dc\tcvac",
    ):
        if forbidden in text:
            raise SystemExit(f"intrusive high-VA diagnostic unexpectedly present: {forbidden}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <arch/arm64/kernel/head.S>")

    head = Path(sys.argv[1])
    instrument_head(head)
    print(f"instrumented {head} with pure HG680-KA high-VA J probe")


if __name__ == "__main__":
    main()
