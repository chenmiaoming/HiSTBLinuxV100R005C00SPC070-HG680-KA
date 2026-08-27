/*
 * Copyright (c) 2015, ARM Limited and Contributors. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * Redistributions of source code must retain the above copyright notice, this
 * list of conditions and the following disclaimer.
 *
 * Redistributions in binary form must reproduce the above copyright notice,
 * this list of conditions and the following disclaimer in the documentation
 * and/or other materials provided with the distribution.
 *
 * Neither the name of ARM nor the names of its contributors may be used
 * to endorse or promote products derived from this software without specific
 * prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

#include <arm_gic.h>
#include <arch.h>
#include <arch_helpers.h>
#include <assert.h>
#include <bl31.h>
#include <bl_common.h>
#include <console.h>
#include <cortex_a57.h>
#include <cortex_a53.h>
#include <debug.h>
#include <errno.h>
#include <mmio.h>
#include <platform.h>
#include <platform_def.h>
#include <hisi_def.h>
#include <stddef.h>
#include <hisi_private.h>
#include <string.h>

unsigned long __RO_START__;
unsigned long __RO_END__;

unsigned long __COHERENT_RAM_START__;
unsigned long __COHERENT_RAM_END__;

#define BL31_RO_BASE (unsigned long)(&__RO_START__)
#define BL31_RO_LIMIT (unsigned long)(&__RO_END__)
#define BL31_COHERENT_RAM_BASE (unsigned long)(&__COHERENT_RAM_START__)
#define BL31_COHERENT_RAM_LIMIT (unsigned long)(&__COHERENT_RAM_END__)

#define ID_AA64PFR0_ELX_NOT_IMPLEMENTED 0xf

static entry_point_info_t bl33_image_ep_info, bl32_image_ep_info;

extern uint64_t ns_image_entrypoint;

#if DISABLE_TEE == 1
entry_point_info_t *bl31_plat_get_next_image_ep_info(uint32_t type)
{
	return &bl33_image_ep_info;
}
#else
entry_point_info_t *bl31_plat_get_next_image_ep_info(uint32_t type)
{
	if (type == NON_SECURE)
		return &bl33_image_ep_info;

	if (type == SECURE)
		return &bl32_image_ep_info;

	return NULL;
}
#endif

void bl31_early_platform_setup(bl31_params_t *from_bl2,
				void *plat_params_from_bl2)
{
	console_init(HISI_UART0_BASE, HISI_UART_CLOCK, HISI_BAUDRATE);
	plat_crash_console_init();

#if 1
	bl33_image_ep_info = *from_bl2->bl33_ep_info;
	bl32_image_ep_info = *from_bl2->bl32_ep_info;

#if DISABLE_TEE == 1
	SET_SECURITY_STATE(bl33_image_ep_info.h.attr, SECURE);
#else
	{
		uint64_t pfr0 = read_id_aa64pfr0_el1();
		unsigned int el2 = (unsigned int)((pfr0 >> ID_AA64PFR0_EL2_SHIFT) &
						 ID_AA64PFR0_ELX_MASK);

		SET_SECURITY_STATE(bl33_image_ep_info.h.attr, NON_SECURE);

		/*
		 * Factory Fastboot requests EL1 in the BL33 SPSR. Prefer EL2 when
		 * available so Linux keeps the virtualization extensions. TF-A's
		 * context management sets SCR_EL3.HCE for an EL2 target and PSCI uses
		 * the same target level for secondary CPUs.
		 */
		if (el2 != ID_AA64PFR0_ELX_NOT_IMPLEMENTED) {
			bl33_image_ep_info.spsr = SPSR_64(MODE_EL2,
					MODE_SP_ELX, DISABLE_ALL_EXCEPTIONS);
			INFO("BL33 normal-world handoff target: EL2 (PFR0.EL2=0x%x)\n",
				el2);
		} else {
			bl33_image_ep_info.spsr = SPSR_64(MODE_EL1,
					MODE_SP_ELX, DISABLE_ALL_EXCEPTIONS);
			INFO("BL33 normal-world handoff target: EL1 (EL2 absent)\n");
		}
	}
#endif

#else
	bl32_image_ep_info.pc = (uintptr_t)0x7e008000;
	SET_SECURITY_STATE(bl32_image_ep_info.h.attr, SECURE);
	bl32_image_ep_info.spsr = 0;

	bl33_image_ep_info.pc = (uintptr_t)0x1080000;
	bl33_image_ep_info.args.arg0 = (uintptr_t)0x2000000;
	bl33_image_ep_info.spsr = SPSR_64(MODE_EL1,
			MODE_SP_ELX, DISABLE_ALL_EXCEPTIONS);
	SET_SECURITY_STATE(bl33_image_ep_info.h.attr, NON_SECURE);
#endif
}

#if DISABLE_TEE == 1
void bl31_platform_setup(void)
{
	plat_delay_timer_init();

	__asm volatile("mrs     x0, cnthctl_el2\n"
			"orr     x0, x0, #0x3\n"
			"msr     cnthctl_el2, x0\n"
			"msr     cntvoff_el2, xzr\n"
			"msr     cntvoff_el2, x0\n"
			"orr     x0, x0, #0x3\n"
			"msr     cntkctl_el1, x0\n");
}
#else
void bl31_platform_setup(void)
{
	plat_delay_timer_init();
	plat_hisi_gic_init();
	arm_gic_setup();
}
#endif

void bl31_plat_arch_setup(void)
{
	uintptr_t fdt = bl33_image_ep_info.args.arg0;
	uintptr_t bl33_dst = bl33_image_ep_info.args.arg1;
	uintptr_t bl33_src = bl33_image_ep_info.pc;
	uint64_t vendor_bl33_size = bl33_image_ep_info.args.arg2;
	uint64_t bl33_size = vendor_bl33_size;
	uint64_t dtb_size = bl33_image_ep_info.args.arg5;
	uintptr_t atags_end = bl33_image_ep_info.args.arg4;
	uint64_t fdt_max_size = bl33_image_ep_info.args.arg5;

	configure_mmu_el3(BL31_RO_BASE,
			(BL31_COHERENT_RAM_LIMIT - BL31_RO_BASE),
			BL31_RO_BASE,
			BL31_RO_LIMIT,
			BL31_COHERENT_RAM_BASE,
			BL31_COHERENT_RAM_LIMIT);

	/*
	 * Factory Fastboot passes arg2 as BL33 FIP entry size minus the legacy
	 * uImage header, so it contains both payload and trailing DTB. arg0 points
	 * exactly at the DTB. Therefore both component sizes are recoverable from
	 * the source pointers without parsing the FDT header.
	 */
	if ((fdt > bl33_src) && ((uint64_t)(fdt - bl33_src) <= vendor_bl33_size)) {
		bl33_size = (uint64_t)(fdt - bl33_src);
		dtb_size = vendor_bl33_size - bl33_size;
		if ((dtb_size == 0) || (dtb_size > fdt_max_size)) {
			WARN("Invalid derived DTB size %lu; using max %lu Bytes\n",
				(unsigned long)dtb_size,
				(unsigned long)fdt_max_size);
			dtb_size = fdt_max_size;
		}
	} else {
		WARN("Invalid vendor BL33/FDT bounds; using ABI size %lu Bytes\n",
			(unsigned long)vendor_bl33_size);
	}

	INFO("Move bl33 from 0x%lx to 0x%lx, %lu Bytes\n",
		bl33_src, bl33_dst, (unsigned long)bl33_size);
	memmove((void *)bl33_dst, (void *)bl33_src, bl33_size);
	flush_dcache_range(bl33_dst, bl33_size);
	bl33_image_ep_info.pc = bl33_dst;

	INFO("Move dtb from 0x%lx to 0x%lx, %lu Bytes\n",
		fdt, atags_end, (unsigned long)dtb_size);
	memmove((void *)atags_end, (const void *)fdt, dtb_size);
	flush_dcache_range(atags_end, dtb_size);

	/* Linux arm64 boot ABI: x0=DTB and x1-x3 must be zero. */
	bl33_image_ep_info.args.arg0 = atags_end;
	bl33_image_ep_info.args.arg1 = 0;
	bl33_image_ep_info.args.arg2 = 0;
	bl33_image_ep_info.args.arg3 = 0;

	INFO("Linux BL33 args: x0=0x%lx, x1=x2=x3=0\n", atags_end);
}
