/*
 * "Hello, world!" payload for Windows — minimal PIC blob using TEB walk.
 *
 * Resolves GetStdHandle, WriteFile, and ExitProcess from kernel32.dll
 * via PEB/TEB walk with DJB2 hash-based function resolution. No imports,
 * no IAT, no static linking to any Windows library.
 */

#include "picblobs/os/windows.h"
#include "picblobs/reloc.h"
#include "picblobs/section.h"
#include "picblobs/types.h"
#include "picblobs/win/resolve.h"

/* DJB2 hashes — precomputed at build time (REQ-006). */
#define HASH_KERNEL32_DLL 0x7040EE75   /* djb2("kernel32.dll") lowercase */
#define HASH_GET_STD_HANDLE 0xF178843C /* djb2("GetStdHandle") */
#define HASH_WRITE_FILE 0x663CECB0     /* djb2("WriteFile") */
#define HASH_EXIT_PROCESS 0xB769339E   /* djb2("ExitProcess") */

/* Windows constants. */
#define STD_OUTPUT_HANDLE ((unsigned long)-11)

/* Windows API function pointer types. */
typedef void *(*fn_GetStdHandle)(unsigned long nStdHandle);
typedef int (*fn_WriteFile)(void *hFile, const void *lpBuffer,
	unsigned long nNumberOfBytesToWrite,
	unsigned long *lpNumberOfBytesWritten, void *lpOverlapped);
typedef void (*fn_ExitProcess)(unsigned int uExitCode);

PIC_RODATA
static const char msg[] = "Hello, world!\n";

PIC_ENTRY
void _start(void)
{
	PIC_SELF_RELOCATE();

	/* Resolve kernel32.dll functions via TEB → PEB → export table. */
	fn_GetStdHandle pGetStdHandle = (fn_GetStdHandle)pic_resolve(
		HASH_KERNEL32_DLL, HASH_GET_STD_HANDLE);
	fn_WriteFile pWriteFile =
		(fn_WriteFile)pic_resolve(HASH_KERNEL32_DLL, HASH_WRITE_FILE);
	fn_ExitProcess pExitProcess = (fn_ExitProcess)pic_resolve(
		HASH_KERNEL32_DLL, HASH_EXIT_PROCESS);

	if (!pGetStdHandle || !pWriteFile || !pExitProcess) {
		/* Resolution failed — nothing we can do without APIs. */
		for (;;)
			;
	}

	void *stdout_handle = pGetStdHandle(STD_OUTPUT_HANDLE);

	unsigned long written = 0;
	pWriteFile(stdout_handle, msg, sizeof(msg) - 1, &written, PIC_NULL);

	pExitProcess(0);
}
