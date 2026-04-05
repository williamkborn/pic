/*
 * Windows test runner — mock TEB/PEB environment on Linux.
 *
 * This runner is a cross-compiled freestanding Linux binary that
 * constructs a synthetic Windows environment (fake TEB, PEB, module
 * list, export tables with DJB2-matched function names) and then
 * executes a Windows-targeting blob within it.
 *
 * Supports: x86_64, i686, aarch64.
 *
 * Usage: ./runner <blob.bin>
 */

#include "picblobs/os/linux.h"
#include "picblobs/sys/close.h"
#include "picblobs/sys/exit.h"
#include "picblobs/sys/exit_group.h"
#include "picblobs/sys/lseek.h"
#include "picblobs/sys/mmap.h"
#include "picblobs/sys/mprotect.h"
#include "picblobs/sys/open.h"
#include "picblobs/sys/read.h"
#include "picblobs/sys/write.h"
#include "picblobs/syscall.h"
#include "picblobs/types.h"

#define RUNNER_ERROR 127

/*
 * PIC_WINAPI — mock functions must use the same calling convention
 * as the blobs that call them. On x86_64, blobs use ms_abi for
 * Windows API calls; on i686/aarch64 it's a no-op.
 */
#if defined(__x86_64__)
#define PIC_WINAPI __attribute__((ms_abi))
#else
#define PIC_WINAPI
#endif

/* ---------- Architecture-specific TEB base setup ---------- */

#if defined(__x86_64__)

#define __NR_arch_prctl 158
#define ARCH_SET_GS 0x1001

static long set_teb_base(void *teb)
{
	return pic_syscall2(__NR_arch_prctl, ARCH_SET_GS, (long)teb);
}

#elif defined(__i386__)

/*
 * i686: set fs base via set_thread_area or arch_prctl.
 * QEMU user-static supports arch_prctl on i386 for setting
 * the segment base.  Fallback: use set_thread_area (syscall 243).
 *
 * We use modify_ldt (syscall 123) to install an LDT entry,
 * then load fs with the selector.
 */

struct user_desc {
	unsigned int entry_number;
	unsigned int base_addr;
	unsigned int limit;
	unsigned int seg_32bit : 1;
	unsigned int contents : 2;
	unsigned int read_exec_only : 1;
	unsigned int limit_in_pages : 1;
	unsigned int seg_not_present : 1;
	unsigned int useable : 1;
};

#define __NR_set_thread_area 243

static long set_teb_base(void *teb)
{
	struct user_desc desc;
	for (int i = 0; i < (int)sizeof(desc); i++)
		((char *)&desc)[i] = 0;
	desc.entry_number = (unsigned int)-1; /* kernel picks a free slot */
	desc.base_addr = (unsigned int)(unsigned long)teb;
	desc.limit = 0xfffff;
	desc.seg_32bit = 1;
	desc.limit_in_pages = 1;
	desc.useable = 1;

	long ret = pic_syscall1(__NR_set_thread_area, (long)&desc);
	if (ret < 0)
		return ret;

	/* Load the new selector into fs.
	 * Selector = (entry_number << 3) | 3  (RPL=3, LDT bit=0 for GDT). */
	unsigned short sel = (unsigned short)((desc.entry_number << 3) | 3);
	__asm__ volatile("mov %0, %%fs" : : "r"(sel));
	return 0;
}

#elif defined(__aarch64__)

/*
 * aarch64: set x18 (the platform register) to point at the mock TEB.
 * On real Windows ARM64, x18 holds the TEB pointer. GCC reserves x18
 * and never uses it as a scratch register, so this is safe.
 */

static long set_teb_base(void *teb)
{
	__asm__ volatile("mov x18, %0" : : "r"(teb));
	return 0;
}

#else
#error "Windows runner: unsupported architecture"
#endif

/* ---------- Mock Windows API implementations ---------- */

static void *mock_GetStdHandle(unsigned long nStdHandle)
{
	if (nStdHandle == (unsigned long)-11)
		return (void *)1; /* stdout */
	if (nStdHandle == (unsigned long)-12)
		return (void *)2; /* stderr */
	if (nStdHandle == (unsigned long)-10)
		return (void *)0; /* stdin */
	return (void *)-1;	  /* INVALID_HANDLE_VALUE */
}

static void *mock_VirtualAlloc(void *lpAddress, pic_uintptr dwSize,
	unsigned long flAllocationType, unsigned long flProtect)
{
	(void)lpAddress;
	(void)flAllocationType;

	/* Map protection flags: any combo with EXEC gets RWX. */
	int prot = PIC_PROT_READ | PIC_PROT_WRITE;
	if (flProtect == 0x10 || flProtect == 0x20 || flProtect == 0x40)
		prot |= PIC_PROT_EXEC;

	void *mem = pic_mmap(PIC_NULL, (pic_size_t)dwSize, prot,
		PIC_MAP_PRIVATE | PIC_MAP_ANONYMOUS, -1, 0);
	if ((long)mem == -1)
		return PIC_NULL;
	return mem;
}

static int mock_WriteFile(void *hFile, const void *lpBuffer,
	unsigned long nNumberOfBytesToWrite,
	unsigned long *lpNumberOfBytesWritten, void *lpOverlapped)
{
	(void)lpOverlapped;
	long ret = pic_write(
		(int)(long)hFile, lpBuffer, (pic_size_t)nNumberOfBytesToWrite);
	if (ret < 0) {
		if (lpNumberOfBytesWritten)
			*lpNumberOfBytesWritten = 0;
		return 0;
	}
	if (lpNumberOfBytesWritten)
		*lpNumberOfBytesWritten = (unsigned long)ret;
	return 1;
}

static void mock_ExitProcess(unsigned int uExitCode)
{
	pic_exit_group((int)uExitCode);
}

/* ---------- Mock PE image builder ---------- */

/*
 * Mock PE image layout (4096 bytes):
 *   +0x000: DOS header (e_lfanew at +0x3C)
 *   +0x080: PE signature + COFF header + Optional header
 *   +0x200: Export directory (40 bytes)
 *   +0x228: Export name strings
 *   +0x280: AddressOfFunctions table
 *   +0x28C: AddressOfNames table
 *   +0x298: AddressOfNameOrdinals table
 *   +0x300: Trampolines
 *
 * Export names (alphabetical): ExitProcess, GetStdHandle, VirtualAlloc,
 *                              WriteFile
 */

#define MOCK_PE_SIZE 4096
#define PE_SIG_OFFSET 0x80
#define OPT_HDR_OFFSET 0x98
#define EXPORT_DIR_OFF 0x200
#define NAME_STR_OFF 0x228
#define FUNC_TBL_OFF 0x2A0
#define NAME_TBL_OFF 0x2B0
#define ORD_TBL_OFF 0x2C0
#define TRAMP_OFF 0x300

static void pe_write32(pic_u8 *base, int offset, pic_u32 val)
{
	base[offset + 0] = (pic_u8)(val);
	base[offset + 1] = (pic_u8)(val >> 8);
	base[offset + 2] = (pic_u8)(val >> 16);
	base[offset + 3] = (pic_u8)(val >> 24);
}

static void pe_write16(pic_u8 *base, int offset, pic_u16 val)
{
	base[offset + 0] = (pic_u8)(val);
	base[offset + 1] = (pic_u8)(val >> 8);
}

static int pe_write_str(pic_u8 *base, int offset, const char *str)
{
	int i = 0;
	while (str[i]) {
		base[offset + i] = (pic_u8)str[i];
		i++;
	}
	base[offset + i] = 0;
	return i + 1;
}

/*
 * Write an architecture-specific trampoline that jumps to `target`.
 * Returns the number of bytes written.
 */
static int write_trampoline(pic_u8 *dest, void *target)
{
#if defined(__x86_64__)
	/*
	 * MS ABI → SysV ABI thunk for mock functions.
	 *
	 * The blob calls through ms_abi function pointers (rcx, rdx, r8, r9,
	 * [rsp+0x28]). The mock functions use SysV ABI (rdi, rsi, rdx, rcx,
	 * r8). This thunk translates args AND preserves rdi/rsi which are
	 * non-volatile in MS ABI but volatile in SysV.
	 *
	 *   push rdi             ; save (ms_abi non-volatile)
	 *   push rsi             ; save (ms_abi non-volatile)
	 *   mov rdi, rcx         ; 1st arg
	 *   mov rsi, rdx         ; 2nd arg
	 *   mov rdx, r8          ; 3rd arg
	 *   mov rcx, r9          ; 4th arg
	 *   mov r8, [rsp+0x38]   ; 5th arg (+0x28 shadow + 2 pushes)
	 *   movabs rax, imm64
	 *   call rax             ; call mock (preserves our pushes)
	 *   pop rsi              ; restore
	 *   pop rdi              ; restore
	 *   ret
	 */
	pic_u64 addr = (pic_u64)(pic_uintptr)target;
	int i = 0;
	/* push rdi */
	dest[i++] = 0x57;
	/* push rsi */
	dest[i++] = 0x56;
	/* mov rdi, rcx */
	dest[i++] = 0x48; dest[i++] = 0x89; dest[i++] = 0xcf;
	/* mov rsi, rdx */
	dest[i++] = 0x48; dest[i++] = 0x89; dest[i++] = 0xd6;
	/* mov rdx, r8 */
	dest[i++] = 0x4c; dest[i++] = 0x89; dest[i++] = 0xc2;
	/* mov rcx, r9 */
	dest[i++] = 0x4c; dest[i++] = 0x89; dest[i++] = 0xc9;
	/* mov r8, [rsp+0x38] (0x28 shadow + 0x08 ret + 0x08 two pushes) */
	dest[i++] = 0x4c; dest[i++] = 0x8b; dest[i++] = 0x44;
	dest[i++] = 0x24; dest[i++] = 0x38;
	/* movabs rax, imm64 */
	dest[i++] = 0x48; dest[i++] = 0xb8;
	dest[i++] = (pic_u8)(addr);
	dest[i++] = (pic_u8)(addr >> 8);
	dest[i++] = (pic_u8)(addr >> 16);
	dest[i++] = (pic_u8)(addr >> 24);
	dest[i++] = (pic_u8)(addr >> 32);
	dest[i++] = (pic_u8)(addr >> 40);
	dest[i++] = (pic_u8)(addr >> 48);
	dest[i++] = (pic_u8)(addr >> 56);
	/* call rax */
	dest[i++] = 0xff; dest[i++] = 0xd0;
	/* pop rsi */
	dest[i++] = 0x5e;
	/* pop rdi */
	dest[i++] = 0x5f;
	/* ret */
	dest[i++] = 0xc3;
	return i; /* 34 bytes */

#elif defined(__i386__)
	/* mov eax, imm32; jmp eax (7 bytes) */
	pic_u32 addr = (pic_u32)(pic_uintptr)target;
	dest[0] = 0xb8;
	dest[1] = (pic_u8)(addr);
	dest[2] = (pic_u8)(addr >> 8);
	dest[3] = (pic_u8)(addr >> 16);
	dest[4] = (pic_u8)(addr >> 24);
	dest[5] = 0xff;
	dest[6] = 0xe0;
	return 7;

#elif defined(__aarch64__)
	/*
	 * ldr x9, .+8; br x9; .quad addr  (16 bytes)
	 * The literal pool immediately follows the branch.
	 */
	pic_u64 addr = (pic_u64)(pic_uintptr)target;
	/* ldr x9, #8  (PC-relative load, offset = +8 bytes = 2 instructions) */
	dest[0] = 0x49;
	dest[1] = 0x00;
	dest[2] = 0x00;
	dest[3] = 0x58;
	/* br x9 */
	dest[4] = 0x20;
	dest[5] = 0x01;
	dest[6] = 0x1f;
	dest[7] = 0xd6;
	/* 8-byte address literal */
	dest[8] = (pic_u8)(addr);
	dest[9] = (pic_u8)(addr >> 8);
	dest[10] = (pic_u8)(addr >> 16);
	dest[11] = (pic_u8)(addr >> 24);
	dest[12] = (pic_u8)(addr >> 32);
	dest[13] = (pic_u8)(addr >> 40);
	dest[14] = (pic_u8)(addr >> 48);
	dest[15] = (pic_u8)(addr >> 56);
	return 16;

#endif
}

/* Max trampoline size across all architectures.
 * x86_64 ABI thunk is 34 bytes; i686/aarch64 are 7/16 bytes. */
#define TRAMP_STRIDE 48

static pic_u8 *build_mock_pe(void)
{
	pic_u8 *pe = (pic_u8 *)pic_mmap(PIC_NULL, MOCK_PE_SIZE,
		PIC_PROT_READ | PIC_PROT_WRITE | PIC_PROT_EXEC,
		PIC_MAP_PRIVATE | PIC_MAP_ANONYMOUS, -1, 0);
	if ((long)pe == -1)
		return PIC_NULL;

	for (int i = 0; i < MOCK_PE_SIZE; i++)
		pe[i] = 0;

	/* DOS header: e_lfanew at +0x3C. */
	pe_write32(pe, 0x3C, PE_SIG_OFFSET);

	/* PE signature "PE\0\0". */
	pe[PE_SIG_OFFSET + 0] = 'P';
	pe[PE_SIG_OFFSET + 1] = 'E';

	/* COFF header: SizeOfOptionalHeader at PE_SIG+4+16. */
	pe_write16(pe, PE_SIG_OFFSET + 4 + 16, 0xF0);

	/* Optional header magic. */
#if PIC_ARCH_IS_32BIT
	pe_write16(pe, OPT_HDR_OFFSET, 0x010B); /* PE32 */
	/* DataDirectory[0] at optional_header + 0x60. */
	pe_write32(pe, OPT_HDR_OFFSET + 0x60, EXPORT_DIR_OFF);
	pe_write32(pe, OPT_HDR_OFFSET + 0x64, 40);
#else
	pe_write16(pe, OPT_HDR_OFFSET, 0x020B); /* PE32+ */
	/* DataDirectory[0] at optional_header + 0x70. */
	pe_write32(pe, OPT_HDR_OFFSET + 0x70, EXPORT_DIR_OFF);
	pe_write32(pe, OPT_HDR_OFFSET + 0x74, 40);
#endif

	/* Export name strings (alphabetically sorted). */
	int name_off = NAME_STR_OFF;
	int exit_process_off = name_off;
	name_off += pe_write_str(pe, name_off, "ExitProcess");
	int get_std_handle_off = name_off;
	name_off += pe_write_str(pe, name_off, "GetStdHandle");
	int virtual_alloc_off = name_off;
	name_off += pe_write_str(pe, name_off, "VirtualAlloc");
	int write_file_off = name_off;
	name_off += pe_write_str(pe, name_off, "WriteFile");
	(void)name_off;

	/* Trampolines (same order as names: alphabetical). */
	int off = TRAMP_OFF;
	write_trampoline(pe + off, (void *)mock_ExitProcess);
	off += TRAMP_STRIDE;
	write_trampoline(pe + off, (void *)mock_GetStdHandle);
	off += TRAMP_STRIDE;
	write_trampoline(pe + off, (void *)mock_VirtualAlloc);
	off += TRAMP_STRIDE;
	write_trampoline(pe + off, (void *)mock_WriteFile);

	/* Export directory header. */
	pe_write32(pe, EXPORT_DIR_OFF + 0x18, 4); /* NumberOfNames */
	pe_write32(pe, EXPORT_DIR_OFF + 0x1C, FUNC_TBL_OFF);
	pe_write32(pe, EXPORT_DIR_OFF + 0x20, NAME_TBL_OFF);
	pe_write32(pe, EXPORT_DIR_OFF + 0x24, ORD_TBL_OFF);

	/* AddressOfFunctions (RVAs to trampolines). */
	pe_write32(pe, FUNC_TBL_OFF + 0, TRAMP_OFF + 0 * TRAMP_STRIDE);
	pe_write32(pe, FUNC_TBL_OFF + 4, TRAMP_OFF + 1 * TRAMP_STRIDE);
	pe_write32(pe, FUNC_TBL_OFF + 8, TRAMP_OFF + 2 * TRAMP_STRIDE);
	pe_write32(pe, FUNC_TBL_OFF + 12, TRAMP_OFF + 3 * TRAMP_STRIDE);

	/* AddressOfNames (RVAs to name strings). */
	pe_write32(pe, NAME_TBL_OFF + 0, (pic_u32)exit_process_off);
	pe_write32(pe, NAME_TBL_OFF + 4, (pic_u32)get_std_handle_off);
	pe_write32(pe, NAME_TBL_OFF + 8, (pic_u32)virtual_alloc_off);
	pe_write32(pe, NAME_TBL_OFF + 12, (pic_u32)write_file_off);

	/* AddressOfNameOrdinals. */
	pe_write16(pe, ORD_TBL_OFF + 0, 0);
	pe_write16(pe, ORD_TBL_OFF + 2, 1);
	pe_write16(pe, ORD_TBL_OFF + 4, 2);
	pe_write16(pe, ORD_TBL_OFF + 6, 3);

	return pe;
}

/* ---------- Mock TEB/PEB/LDR structures ---------- */

#define MOCK_REGION_SIZE 4096

#define TEB_OFF 0x000
#define PEB_OFF 0x100
#define LDR_OFF 0x200
#define MODULE_ENTRY_OFF 0x300
#define DLL_NAME_OFF 0x400

static pic_u16 write_utf16le(pic_u8 *dest, const char *str)
{
	int i = 0;
	while (str[i]) {
		dest[i * 2] = (pic_u8)str[i];
		dest[i * 2 + 1] = 0;
		i++;
	}
	return (pic_u16)(i * 2);
}

static void write_ptr(pic_u8 *base, int offset, void *ptr)
{
#if PIC_ARCH_IS_32BIT
	pic_u32 val = (pic_u32)(pic_uintptr)ptr;
	base[offset + 0] = (pic_u8)(val);
	base[offset + 1] = (pic_u8)(val >> 8);
	base[offset + 2] = (pic_u8)(val >> 16);
	base[offset + 3] = (pic_u8)(val >> 24);
#else
	pic_u64 val = (pic_u64)(pic_uintptr)ptr;
	base[offset + 0] = (pic_u8)(val);
	base[offset + 1] = (pic_u8)(val >> 8);
	base[offset + 2] = (pic_u8)(val >> 16);
	base[offset + 3] = (pic_u8)(val >> 24);
	base[offset + 4] = (pic_u8)(val >> 32);
	base[offset + 5] = (pic_u8)(val >> 40);
	base[offset + 6] = (pic_u8)(val >> 48);
	base[offset + 7] = (pic_u8)(val >> 56);
#endif
}

static pic_u8 *build_mock_env(pic_u8 *mock_pe)
{
	pic_u8 *region = (pic_u8 *)pic_mmap(PIC_NULL, MOCK_REGION_SIZE,
		PIC_PROT_READ | PIC_PROT_WRITE,
		PIC_MAP_PRIVATE | PIC_MAP_ANONYMOUS, -1, 0);
	if ((long)region == -1)
		return PIC_NULL;

	for (int i = 0; i < MOCK_REGION_SIZE; i++)
		region[i] = 0;

	pic_u8 *teb = region + TEB_OFF;
	pic_u8 *peb = region + PEB_OFF;
	pic_u8 *ldr = region + LDR_OFF;
	pic_u8 *entry = region + MODULE_ENTRY_OFF;
	pic_u8 *dll_name_buf = region + DLL_NAME_OFF;

	pic_u16 dll_name_bytes = write_utf16le(dll_name_buf, "kernel32.dll");

	/*
	 * TEB layout:
	 *   64-bit: +0x30 = self, +0x60 = PEB
	 *   32-bit: +0x18 = self, +0x30 = PEB
	 */
#if PIC_ARCH_IS_32BIT
	write_ptr(teb, 0x18, teb);
	write_ptr(teb, 0x30, peb);
#else
	write_ptr(teb, 0x30, teb);
	write_ptr(teb, 0x60, peb);
#endif

	/*
	 * PEB layout:
	 *   64-bit: +0x18 = Ldr
	 *   32-bit: +0x0C = Ldr
	 */
#if PIC_ARCH_IS_32BIT
	write_ptr(peb, 0x0C, ldr);
#else
	write_ptr(peb, 0x18, ldr);
#endif

	/*
	 * PEB_LDR_DATA → InMemoryOrderModuleList:
	 *   64-bit: +0x20
	 *   32-bit: +0x14
	 */
#if PIC_ARCH_IS_32BIT
	pic_u8 *list_head = ldr + 0x14;
#else
	pic_u8 *list_head = ldr + 0x20;
#endif
	write_ptr(list_head, 0x00, entry);
	write_ptr(list_head, sizeof(void *), entry);

	/*
	 * LDR_DATA_TABLE_ENTRY (from InMemoryOrderLinks):
	 *   Flink/Blink at +0x00/+ptr_size
	 *   DllBase:     64-bit +0x20, 32-bit +0x10
	 *   BaseDllName: 64-bit +0x48, 32-bit +0x24
	 */
	write_ptr(entry, 0x00, list_head);
	write_ptr(entry, sizeof(void *), list_head);

#if PIC_ARCH_IS_32BIT
	write_ptr(entry, 0x10, mock_pe);
	pic_u8 *ustr = entry + 0x24;
#else
	write_ptr(entry, 0x20, mock_pe);
	pic_u8 *ustr = entry + 0x48;
#endif

	/* UNICODE_STRING: Length, MaximumLength, Buffer. */
	ustr[0] = (pic_u8)(dll_name_bytes);
	ustr[1] = (pic_u8)(dll_name_bytes >> 8);
	ustr[2] = (pic_u8)(dll_name_bytes + 2);
	ustr[3] = 0;

	/* Buffer pointer: at +4 (32-bit) or +8 (64-bit). */
#if PIC_ARCH_IS_32BIT
	write_ptr(ustr, 0x04, dll_name_buf);
#else
	write_ptr(ustr, 0x08, dll_name_buf);
#endif

	return teb;
}

/* ---------- Blob loader ---------- */

static long file_size(int fd)
{
	long end = pic_lseek(fd, 0, PIC_SEEK_END);
	if (end < 0)
		return -1;
	if (pic_lseek(fd, 0, PIC_SEEK_SET) < 0)
		return -1;
	return end;
}

static long read_all(int fd, void *buf, pic_size_t count)
{
	pic_u8 *p = (pic_u8 *)buf;
	pic_size_t done = 0;
	while (done < count) {
		long n = pic_read(fd, p + done, count - done);
		if (n <= 0)
			return -1;
		done += (pic_size_t)n;
	}
	return (long)done;
}

/* ---------- _start and runner_main ---------- */

#if defined(__x86_64__)
#include "start/x86_64.h"
#elif defined(__i386__)
#include "start/i386.h"
#elif defined(__aarch64__)
#include "start/aarch64.h"
#else
#error "Windows runner: unsupported architecture for _start"
#endif

int runner_main(int argc, char **argv)
{
	if (argc < 2)
		pic_exit_group(RUNNER_ERROR);

	pic_u8 *mock_pe = build_mock_pe();
	if (!mock_pe)
		pic_exit_group(RUNNER_ERROR);

	pic_u8 *teb = build_mock_env(mock_pe);
	if (!teb)
		pic_exit_group(RUNNER_ERROR);

	long ret = set_teb_base(teb);
	if (ret < 0)
		pic_exit_group(RUNNER_ERROR);

	int fd = (int)pic_open(argv[1], PIC_O_RDONLY, 0);
	if (fd < 0)
		pic_exit_group(RUNNER_ERROR);

	long size = file_size(fd);
	if (size <= 0) {
		pic_close(fd);
		pic_exit_group(RUNNER_ERROR);
	}

	void *blob = pic_mmap(PIC_NULL, (pic_size_t)size,
		PIC_PROT_READ | PIC_PROT_WRITE | PIC_PROT_EXEC,
		PIC_MAP_PRIVATE | PIC_MAP_ANONYMOUS, -1, 0);
	if ((long)blob == -1) {
		pic_close(fd);
		pic_exit_group(RUNNER_ERROR);
	}

	if (read_all(fd, blob, (pic_size_t)size) < 0) {
		pic_close(fd);
		pic_exit_group(RUNNER_ERROR);
	}

	pic_close(fd);

	((void (*)(void))blob)();

	pic_exit_group(RUNNER_ERROR);
}
