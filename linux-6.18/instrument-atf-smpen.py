#!/usr/bin/env python3
"""Instrument the HG680-KA TF-A PSCI secondary finish path.

Keep this diagnostic deliberately primitive: the secondary CPU is in TF-A's
PSCI power-on completion path while CPU0 is already running Linux. Using the
TF-A INFO()/console machinery here can perturb the path we are trying to
observe, so emit single characters directly to the PL011 data register.

The Hi3798MV310 factory boot path uses a warm reset and its Cortex-A53 reset
handler enables SMPEN but does not explicitly invalidate the local I-cache.
Invalidate the secondary PE's I-cache immediately before returning to Linux so
a powered-off/warm-reset core cannot execute stale instructions from a previous
kernel image or from text patched by Linux alternatives.

Output for the first secondary is expected to look like:

    S1 F G H I A1 B1 C1 U1 V1 W1 X1 Y1 Z1 D1 E1

S0/S1 reports Cortex-A53 CPUECTLR_EL1.SMPEN. F/G/H bracket the two per-CPU
GIC setup calls. I means local I-cache invalidation completed. Linux's A-E and
U-Z markers take over after TF-A returns to the non-secure secondary entry.
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

    injected = """void hisi_pwr_domain_on_finish(const psci_power_state_t *target_state)\n{\n#if DISABLE_TEE == 0\n\tuint64_t cpuectlr;\n\n\t/* HG680-KA SMPEN diagnostic. Do not use INFO()/console locks here: CPU0\n\t * is already in Linux while this secondary is completing PSCI CPU_ON. */\n\t__asm volatile(\"mrs %0, S3_1_C15_C2_1\" : \"=r\" (cpuectlr));\n\twritel('S', HISI_UART0_BASE);\n\twritel((cpuectlr & (1ULL << 6)) ? '1' : '0', HISI_UART0_BASE);\n\twritel(' ', HISI_UART0_BASE);\n\n\t/* F/G/H bracket the two GICv2 per-CPU setup calls. */\n\twritel('F', HISI_UART0_BASE);\n\twritel(' ', HISI_UART0_BASE);\n\tarm_gic_cpuif_setup();\n\twritel('G', HISI_UART0_BASE);\n\twritel(' ', HISI_UART0_BASE);\n\tarm_gic_pcpu_distif_setup();\n\twritel('H', HISI_UART0_BASE);\n\twritel(' ', HISI_UART0_BASE);\n\n\t/* The platform reaches secondary CPUs through a warm-reset/power-on path.\n\t * cortex_a53_reset_func() enables SMPEN but does not invalidate the local\n\t * I-cache. Drop any stale lines before ERET to Linux. */\n\t__asm volatile(\"ic iallu\\n\"\n\t\t       \"dsb sy\\n\"\n\t\t       \"isb\\n\"\n\t\t       : : : \"memory\");\n\twritel('I', HISI_UART0_BASE);\n\twritel(' ', HISI_UART0_BASE);\n"""

    path.write_text(text.replace(anchor, injected, 1))
    print(f"instrumented {path} with SMPEN/GIC/I-cache diagnostics")


if __name__ == "__main__":
    main()
