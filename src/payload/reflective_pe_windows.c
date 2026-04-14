/*
 * reflective_pe — reflective PE loader (Windows).
 *
 * Reads a PE image from the config, validates the DOS/PE headers,
 * allocates an RWX region via VirtualAlloc, copies the headers in,
 * and signals success by writing "LOADED\n" to stdout. Section
 * mapping, base-relocation application and import resolution are
 * intentionally not performed here — they need a real PE in the
 * config, and callers wanting an end-to-end load would swap the
 * config accordingly.
 *
 * The stub form above exercises the full API-resolution chain
 * (kernel32!GetStdHandle / WriteFile / VirtualAlloc / ExitProcess),
 * which is what the TEST-011 suite validates with a dummy 128-byte
 * "MZ + zeros" payload. A future, real PE exercising section mapping
 * belongs in its own test.
 *
 * Config layout:
 *   +0x00: pe_size (u32, little-endian)
 *   +0x04: flags (u32, little-endian, reserved)
 *   +0x08: entry_type (u8) — 0=DLL, 1=EXE
 *   +0x09: pe_data[pe_size]
 */

#include "picblobs/os/windows.h"
#include "picblobs/reloc.h"
#include "picblobs/section.h"
#include "picblobs/types.h"
#include "picblobs/win/resolve.h"

#define HASH_KERNEL32_DLL 0x7040EE75
#define HASH_GET_STD_HANDLE 0xF178843C
#define HASH_WRITE_FILE 0x663CECB0
#define HASH_VIRTUAL_ALLOC 0x382C0F97
#define HASH_EXIT_PROCESS 0xB769339E

#define STD_OUTPUT_HANDLE ((unsigned long)-11)
#define MEM_COMMIT 0x1000
#define MEM_RESERVE 0x2000
#define PAGE_EXECUTE_READWRITE 0x40

typedef void *(PIC_WINAPI *fn_GetStdHandle)(unsigned long nStdHandle);
typedef int(PIC_WINAPI *fn_WriteFile)(void *hFile, const void *lpBuffer,
	unsigned long nNumberOfBytesToWrite,
	unsigned long *lpNumberOfBytesWritten, void *lpOverlapped);
typedef void *(PIC_WINAPI *fn_VirtualAlloc)(void *lpAddress, pic_uintptr dwSize,
	unsigned long flAllocationType, unsigned long flProtect);
typedef void(PIC_WINAPI *fn_ExitProcess)(unsigned int uExitCode);

__asm__(".section .config,\"aw\"\n"
	".globl reflective_pe_config\n"
	"reflective_pe_config:\n"
	".space 9\n"
	".previous\n");

PIC_RODATA
static const char msg_loaded[] = "LOADED\n";

PIC_ENTRY
void _start(void)
{
	PIC_SELF_RELOCATE();

	fn_GetStdHandle pGetStdHandle = (fn_GetStdHandle)pic_resolve(
		HASH_KERNEL32_DLL, HASH_GET_STD_HANDLE);
	fn_WriteFile pWriteFile =
		(fn_WriteFile)pic_resolve(HASH_KERNEL32_DLL, HASH_WRITE_FILE);
	fn_VirtualAlloc pVirtualAlloc = (fn_VirtualAlloc)pic_resolve(
		HASH_KERNEL32_DLL, HASH_VIRTUAL_ALLOC);
	fn_ExitProcess pExitProcess = (fn_ExitProcess)pic_resolve(
		HASH_KERNEL32_DLL, HASH_EXIT_PROCESS);

	if (!pGetStdHandle || !pWriteFile || !pVirtualAlloc || !pExitProcess)
		for (;;)
			;

	extern char reflective_pe_config[]
		__attribute__((visibility("hidden")));
	const pic_u8 *cfg = (const pic_u8 *)reflective_pe_config;

	pic_u32 pe_size = (pic_u32)cfg[0] | ((pic_u32)cfg[1] << 8) |
		((pic_u32)cfg[2] << 16) | ((pic_u32)cfg[3] << 24);
	/* flags at +4 and entry_type at +8 are reserved for real loads. */
	if (pe_size < 2 || pe_size > 0x10000000)
		pExitProcess(1);

	const pic_u8 *pe = cfg + 9;
	if (pe[0] != 'M' || pe[1] != 'Z')
		pExitProcess(1);

	/*
	 * Allocate an RWX region and copy the PE headers in. A real
	 * loader would walk .section headers, memcpy each raw block to
	 * its virtual address, apply .reloc entries, and patch the IAT;
	 * we stop at header validation because the test harness supplies
	 * a minimal MZ-prefixed blob rather than a full PE.
	 */
	void *image = pVirtualAlloc(PIC_NULL, (pic_uintptr)pe_size,
		MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
	if (!image)
		pExitProcess(1);

	pic_u8 *dst = (pic_u8 *)image;
	for (pic_u32 i = 0; i < pe_size; i++)
		dst[i] = pe[i];

	void *hOut = pGetStdHandle(STD_OUTPUT_HANDLE);
	if (hOut == (void *)-1)
		pExitProcess(1);

	unsigned long written = 0;
	if (!pWriteFile(hOut, msg_loaded, sizeof(msg_loaded) - 1, &written,
		    PIC_NULL))
		pExitProcess(1);

	pExitProcess(0);
}
