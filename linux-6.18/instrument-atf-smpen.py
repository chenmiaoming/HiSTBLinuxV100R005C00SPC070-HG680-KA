#!/usr/bin/env python3
"""Instrument the HG680-KA TF-A PSCI secondary finish path.

The Cortex-A53 requires CPUECTLR_EL1.SMPEN (bit 6) for intra-cluster cache
coherency. Linux secondary CPUs reach the MMU-off path but stall when enabling
cacheable mappings, so verify the bit at the last EL3 stage before returning to
Linux and force it on if firmware reset handling left it clear.
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

    anchor = """void hisi_pwr_domain_on_finish(const psci_power_state_t *target_state)\n{\n#if DISABLE_TEE == 0\n"""
    if text.count(anchor) != 1:
        raise SystemExit(
            f"hisi_pwr_domain_on_finish anchor: expected exactly one match, found {text.count(anchor)}"
        )

    injected = """void hisi_pwr_domain_on_finish(const psci_power_state_t *target_state)\n{\n\tuint64_t cpuectlr;\n\tunsigned int cpu = (unsigned int)(read_mpidr_el1() & MPIDR_CPU_MASK);\n\n\t/* HG680-KA SMPEN diagnostic: Cortex-A53 coherency must be enabled before\n\t * Linux turns on cacheable mappings on a secondary CPU. */\n\t__asm volatile(\"mrs %0, S3_1_C15_C2_1\" : \"=r\" (cpuectlr));\n\tINFO(\"HG680-KA CPU%u CPUECTLR_EL1 SMPEN before=%u raw_lo=0x%x\\n\",\n\t     cpu, (unsigned int)((cpuectlr >> 6) & 1), (unsigned int)cpuectlr);\n\n\tif ((cpuectlr & (1ULL << 6)) == 0) {\n\t\tcpuectlr |= (1ULL << 6);\n\t\t__asm volatile(\"msr S3_1_C15_C2_1, %0\\n\"\n\t\t\t       \"isb\\n\"\n\t\t\t       \"dsb sy\\n\"\n\t\t\t       : : \"r\" (cpuectlr) : \"memory\");\n\t\tINFO(\"HG680-KA CPU%u forced CPUECTLR_EL1.SMPEN=1\\n\", cpu);\n\t}\n#if DISABLE_TEE == 0\n"""

    path.write_text(text.replace(anchor, injected, 1))
    print(f"instrumented {path} with Cortex-A53 SMPEN diagnostic")


if __name__ == "__main__":
    main()
