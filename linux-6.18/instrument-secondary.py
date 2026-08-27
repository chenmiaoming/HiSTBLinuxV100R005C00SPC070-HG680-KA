#!/usr/bin/env python3
"""Inject temporary HG680-KA secondary-CPU UART markers into Linux head.S.

This is intentionally a bring-up-only transformation.  Every anchor must match
exactly once so a kernel source change cannot silently instrument the wrong
place.
"""

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <arch/arm64/kernel/head.S>")

    path = Path(sys.argv[1])
    text = path.read_text()

    macro = r'''
/* HG680-KA temporary secondary CPU bring-up marker. */
	.macro	hg680ka_uart_marker, ch
	movz	x9, #0xf8b0, lsl #16
	mov	w10, #\ch
	str	w10, [x9]
	mrs	x10, mpidr_el1
	and	w10, w10, #0xff
	add	w10, w10, #'0'
	str	w10, [x9]
	mov	w10, #' '
	str	w10, [x9]
	.endm
'''

    text = replace_once(
        text,
        '#include "efi-header.S"\n',
        '#include "efi-header.S"\n' + macro,
        "marker macro",
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
        '\tbl\t__cpu_setup\t\t\t// initialise processor\n\thg680ka_uart_marker 0x44\n\tadrp\tx1, swapper_pg_dir\n',
        "post __cpu_setup",
    )

    path.write_text(text)

    for marker in ("0x41", "0x42", "0x43", "0x44"):
        if f"hg680ka_uart_marker {marker}" not in text:
            raise SystemExit(f"failed to insert marker {marker}")

    print(f"instrumented {path} with HG680-KA secondary markers A-D")


if __name__ == "__main__":
    main()
