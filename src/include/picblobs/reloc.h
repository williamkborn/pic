/*
 * picblobs/reloc.h — self-relocation for PIC blobs.
 *
 * On MIPS32, PIC code uses $t9 to set up $gp, and $gp to access
 * the GOT. When jumping to a blob at an arbitrary address, $t9
 * is not set. PIC_SELF_RELOCATE() fixes $t9 using bal (the only
 * way to discover PC on MIPS without caller cooperation).
 *
 * Additionally, GOT entries contain link-time absolute addresses.
 * After fixing $gp, we patch every GOT entry by adding the load
 * offset (runtime_base - link_time_base).
 *
 * On x86_64, aarch64, ARM, i686: no-op (PC-relative addressing).
 */

#ifndef PICBLOBS_RELOC_H
#define PICBLOBS_RELOC_H

#include "picblobs/arch.h"

#if PIC_ARCH_NEEDS_GOT_RELOC

/*
 * MIPS self-relocation. Must be called BEFORE any global data access,
 * ideally as the very first thing in _start(). The compiler-generated
 * .cpload $t9 prologue runs before our C code, so we need to fix $t9
 * before .cpload. We do this by putting the $t9 fixup into a
 * constructor-like section that the linker places before .text.pic_entry.
 *
 * Actually, we can't run code before .cpload in the same function.
 * So instead: we write _start in assembly ourselves, set $t9 via bal,
 * then call the user's C entry point.
 *
 * The user writes:
 *   PIC_ENTRY void pic_main(void) { ... }
 *
 * On MIPS, PIC_ENTRY emits the function into .text.pic_entry but the
 * actual _start is an asm stub in .text.pic_entry_trampoline that:
 *   1. Uses bal to discover runtime PC
 *   2. Computes runtime _start address
 *   3. Sets $t9 = runtime _start (well, runtime pic_main)
 *   4. Calls pic_main — GCC's .cpload $t9 now works correctly
 *   5. After .cpload, $gp is correct, GOT accesses work
 *
 * BUT: GOT entries still contain link-time absolute addresses!
 * After $gp is set, GOT[msg] = link-time msg address (e.g., 0x60).
 * We need GOT[msg] = runtime msg address = runtime_base + 0x60.
 *
 * So we ALSO need to patch GOT entries. We do this in pic_main
 * before accessing any global data, using $gp (now correct) to
 * find __got_start/__got_end in the GOT, then patching.
 */

/*
 * Step 1: PIC_SELF_RELOCATE() patches GOT entries.
 *         Called from the user's entry function after .cpload ran.
 *         At this point $gp is correct (pointing into the GOT at runtime).
 *         GOT values are link-time absolutes. We add delta to each.
 *
 *         delta = runtime_blob_start - link_time_blob_start
 *               = runtime_blob_start - 0 (our linker script bases at 0)
 *               = runtime_blob_start
 *
 *         We get runtime_blob_start from $t9 minus the offset of the
 *         current function from __blob_start. For _start, that's 0.
 *         But after patching, the GOT entries we used to find
 *         __got_start/__got_end are now double-patched on second call.
 *         Since PIC_SELF_RELOCATE is called once at startup, this is fine.
 */
#define PIC_SELF_RELOCATE()                                                    \
	do {                                                                   \
		unsigned long _got_s, _got_e, _delta;                          \
		/* $gp is set correctly by .cpload $t9 (trampoline set $t9).   \
		 */                                                            \
		/* Load __got_start and __got_end from GOT (link-time values). \
		 */                                                            \
		__asm__ volatile("lw %0, %%got(__got_start)($gp)\n\t"          \
				 "lw %1, %%got(__got_end)($gp)\n\t"            \
			: "=r"(_got_s), "=r"(_got_e));                         \
		/* $s0 = runtime base (delta), set by the MIPS trampoline. */  \
		/* link-time base = 0, so delta = runtime base. */             \
		__asm__ volatile("move %0, $s0" : "=r"(_delta));               \
		if (_delta != 0) {                                             \
			unsigned long *p = (unsigned long *)(_got_s + _delta); \
			unsigned long *e = (unsigned long *)(_got_e + _delta); \
			while (p < e) {                                        \
				*p += _delta;                                  \
				p++;                                           \
			}                                                      \
		}                                                              \
	} while (0)

#else

#define PIC_SELF_RELOCATE() ((void)0)

#endif

#endif /* PICBLOBS_RELOC_H */
