#!/usr/bin/env python3
"""Instrument the HG680-KA TF-A PSCI secondary finish path.

Keep this diagnostic deliberately primitive: the secondary CPU is in TF-A's
PSCI power-on completion path while CPU0 is already running Linux. Using the
TF-A INFO()/console machinery here can perturb the path we are trying to
observe, so emit characters directly to PL011.

Raw DR writes are not safe when markers are emitted back-to-back: PL011 has a
small TX FIFO and a full FIFO can perturb or stall the path under test. Every
character therefore waits for UARTFR.TXFF (bit 5) to clear before writing DR.

Output for the first secondary is expected to look like:

    S1 F G H A1 B1 C1 P1 U1 V1 W1 X1 Y1 Z1 D1 E1

S0/S1 reports Cortex-A53 CPUECTLR_EL1.SMPEN. F/G/H bracket the two per-CPU
GIC setup calls. Linux's A-E/P and U-Z markers take over after TF-A returns to
the non-secure secondary entry point.
"""

from pathlib import Path
import sys

MARKER = "HG680-KA SMPEN diagnostic"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <plat/hisilicon/hi3798mv310/hisi_pm.c>")

    path = Path(sys.argv[1])
    text = path.read_text()

    if MARKER in text:
        print(f"{path}: already instrumented")
        return

    anchor = """void hisi_pwr_domain_on_finish(const psci_power_state_t *target_state)\n{\n#if DISABLE_TEE == 0\n\t/* Enable the gic cpu interface */\n\tarm_gic_cpuif_setup();\n\tarm_gic_pcpu_distif_setup();\n"""
    if text.count(anchor) != 1:
        raise SystemExit(
            f"hisi_pwr_domain_on_finish anchor: expected exactly one match, found {text.count(anchor)}"
        )

    injected = """void hisi_pwr_domain_on_finish(const psci_power_state_t *target_state)\n{\n#if DISABLE_TEE == 0\n\tuint64_t cpuectlr;\n\n\t/* HG680-KA SMPEN diagnostic. Do not use INFO()/console locks here: CPU0\n\t * is already in Linux while this secondary is completing PSCI CPU_ON.\n\t * Poll PL011 UARTFR.TXFF before every DR write so the marker itself can\n\t * never fill the TX FIFO and stall the path under test. */\n#define HG680KA_DIAG_PUTC(ch) do { \\\n\twhile (readl(HISI_UART0_BASE + 0x18) & (1U << 5)) \\\n\t\t; \\\n\twritel((ch), HISI_UART0_BASE); \\\n} while (0)\n\n\t__asm volatile(\"mrs %0, S3_1_C15_C2_1\" : \"=r\" (cpuectlr));\n\tHG680KA_DIAG_PUTC('S');\n\tHG680KA_DIAG_PUTC((cpuectlr & (1ULL << 6)) ? '1' : '0');\n\tHG680KA_DIAG_PUTC(' ');\n\n\t/* F/G/H bracket the two GICv2 per-CPU setup calls. */\n\tHG680KA_DIAG_PUTC('F');\n\tHG680KA_DIAG_PUTC(' ');\n\tarm_gic_cpuif_setup();\n\tHG680KA_DIAG_PUTC('G');\n\tHG680KA_DIAG_PUTC(' ');\n\tarm_gic_pcpu_distif_setup();\n\tHG680KA_DIAG_PUTC('H');\n\tHG680KA_DIAG_PUTC(' ');\n\n#undef HG680KA_DIAG_PUTC\n"""

    path.write_text(text.replace(anchor, injected, 1))
    print(f"instrumented {path} with FIFO-safe SMPEN/GIC diagnostics")


if __name__ == "__main__":
    main()
