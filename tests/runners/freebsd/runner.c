/*
 * FreeBSD test runner — syscall-translating loader on Linux.
 *
 * Loads a FreeBSD-targeting PIC blob, patches FreeBSD syscall numbers
 * to their Linux equivalents in the code, then executes the blob.
 * The blob thinks it's calling FreeBSD syscalls but actually hits
 * the Linux kernel with correct numbers.
 *
 * This runner is hand-written (not generated) because it needs to
 * use Linux syscalls internally while translating FreeBSD numbers
 * in the loaded blob. See generate.py which skips this file.
 *
 * Supports: x86_64, i686, aarch64, armv5, armv7, s390x, mipsel32, mipsbe32.
 *
 * Usage: ./runner <blob.bin>
 */

#include "picblobs/os/linux.h"
#include "picblobs/sys/accept.h"
#include "picblobs/sys/bind.h"
#include "picblobs/sys/close.h"
#include "picblobs/sys/connect.h"
#include "picblobs/sys/exit.h"
#include "picblobs/sys/exit_group.h"
#include "picblobs/sys/listen.h"
#include "picblobs/sys/lseek.h"
#include "picblobs/sys/mmap.h"
#include "picblobs/sys/mprotect.h"
#include "picblobs/sys/munmap.h"
#include "picblobs/sys/open.h"
#include "picblobs/sys/read.h"
#include "picblobs/sys/setsockopt.h"
#include "picblobs/sys/socket.h"
#include "picblobs/sys/write.h"
#include "picblobs/syscall.h"
#include "picblobs/types.h"

#define RUNNER_ERROR 127

struct nr_map {
	pic_u32 freebsd_nr;
	pic_u32 linux_nr;
};

static const struct nr_map syscall_table[] = {
	{1, __NR_exit},
	{3, __NR_read},
	{4, __NR_write},
#ifdef __NR_open
	{5, __NR_open},
#endif
	{6, __NR_close},
#ifdef __NR_lseek
	{478, __NR_lseek},
#endif
#ifdef __NR_llseek
	{478, __NR_llseek},
#endif
	{9, __NR_mmap},
	{74, __NR_mprotect},
	{73, __NR_munmap},
	{97, __NR_socket},
	{98, __NR_connect},
	{30, __NR_accept},
	{104, __NR_bind},
	{106, __NR_listen},
	{105, __NR_setsockopt},
	{431, __NR_exit_group},
};

#define NR_TABLE_SIZE (sizeof(syscall_table) / sizeof(syscall_table[0]))

static inline pic_u32 translate_nr(pic_u32 freebsd_nr)
{
	for (int i = 0; i < (int)NR_TABLE_SIZE; i++)
		if (syscall_table[i].freebsd_nr == freebsd_nr)
			return syscall_table[i].linux_nr;
	return freebsd_nr;
}

static inline void write32_le(pic_u8 *p, pic_u32 v)
{
	p[0] = (pic_u8)v;
	p[1] = (pic_u8)(v >> 8);
	p[2] = (pic_u8)(v >> 16);
	p[3] = (pic_u8)(v >> 24);
}
static inline pic_u32 read32_le(const pic_u8 *p)
{
	return (pic_u32)p[0] | ((pic_u32)p[1] << 8) | ((pic_u32)p[2] << 16) |
		((pic_u32)p[3] << 24);
}
static inline void write32_be(pic_u8 *p, pic_u32 v)
{
	p[0] = (pic_u8)(v >> 24);
	p[1] = (pic_u8)(v >> 16);
	p[2] = (pic_u8)(v >> 8);
	p[3] = (pic_u8)v;
}
static inline pic_u32 read32_be(const pic_u8 *p)
{
	return ((pic_u32)p[0] << 24) | ((pic_u32)p[1] << 16) |
		((pic_u32)p[2] << 8) | (pic_u32)p[3];
}
static inline pic_u16 read16_be(const pic_u8 *p)
{
	return (pic_u16)(((pic_u16)p[0] << 8) | (pic_u16)p[1]);
}
static inline void write16_be(pic_u8 *p, pic_u16 v)
{
	p[0] = (pic_u8)(v >> 8);
	p[1] = (pic_u8)v;
}

#if defined(__x86_64__)
static void patch_syscalls_x86_64(pic_u8 *code, pic_size_t size)
{
	for (pic_size_t i = 0; i + 6 < size; i++) {
		if (code[i] == 0xb8 && code[i + 5] == 0x0f &&
			code[i + 6] == 0x05) {
			pic_u32 nr = read32_le(code + i + 1);
			pic_u32 lnr = translate_nr(nr);
			if (lnr != nr)
				write32_le(code + i + 1, lnr);
		}
	}
}
#elif defined(__i386__)
static void patch_syscalls_i386(pic_u8 *code, pic_size_t size)
{
	for (pic_size_t i = 0; i + 6 < size; i++) {
		if (code[i] == 0xb8 && code[i + 5] == 0xcd &&
			code[i + 6] == 0x80) {
			pic_u32 nr = read32_le(code + i + 1);
			pic_u32 lnr = translate_nr(nr);
			if (lnr != nr)
				write32_le(code + i + 1, lnr);
		}
	}
}
#elif defined(__aarch64__)
static void patch_syscalls_aarch64(pic_u8 *code, pic_size_t size)
{
	for (pic_size_t i = 0; i + 7 < size; i += 4) {
		pic_u32 insn = read32_le(code + i);
		pic_u32 next = read32_le(code + i + 4);
		if ((insn & 0xFFE0001F) == 0xD2800008 && next == 0xD4000001) {
			pic_u32 nr = (insn >> 5) & 0xFFFF;
			pic_u32 lnr = translate_nr(nr);
			if (lnr != nr) {
				insn = (insn & ~(0xFFFF << 5)) | (lnr << 5);
				write32_le(code + i, insn);
			}
		}
	}
}
#elif defined(__arm__)
static void patch_syscalls_arm(pic_u8 *code, pic_size_t size)
{
	for (pic_size_t i = 0; i + 3 < size; i += 2) {
		pic_u16 insn = (pic_u16)code[i] | ((pic_u16)code[i + 1] << 8);
		pic_u16 next =
			(pic_u16)code[i + 2] | ((pic_u16)code[i + 3] << 8);
		if ((insn & 0xFF00) == 0x2700 && next == 0xdf00) {
			pic_u32 nr = insn & 0xFF;
			pic_u32 lnr = translate_nr(nr);
			if (lnr != nr && lnr < 256)
				code[i] = (pic_u8)lnr;
		}
	}
}
#elif defined(__s390x__)
static void patch_syscalls_s390x(pic_u8 *code, pic_size_t size)
{
	for (pic_size_t i = 0; i + 5 < size; i += 2) {
		if (code[i] == 0xa7 && code[i + 1] == 0x19 &&
			code[i + 4] == 0x0a && code[i + 5] == 0x00) {
			pic_u16 nr = read16_be(code + i + 2);
			pic_u32 lnr = translate_nr(nr);
			if (lnr != nr && lnr < 0x8000)
				write16_be(code + i + 2, (pic_u16)lnr);
		}
	}
}
#elif defined(__mips__)
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
static void patch_syscalls_mips_be(pic_u8 *code, pic_size_t size)
{
	for (pic_size_t i = 0; i + 7 < size; i += 4) {
		pic_u32 insn = read32_be(code + i);
		pic_u32 next = read32_be(code + i + 4);
		if ((insn & 0xFFFF0000) == 0x24020000 && next == 0x0000000c) {
			pic_u32 nr = insn & 0xFFFF;
			pic_u32 lnr = translate_nr(nr);
			if (lnr != nr)
				write32_be(code + i,
					(insn & 0xFFFF0000) | (lnr & 0xFFFF));
		}
	}
}
#else
static void patch_syscalls_mips_le(pic_u8 *code, pic_size_t size)
{
	for (pic_size_t i = 0; i + 7 < size; i += 4) {
		pic_u32 insn = read32_le(code + i);
		pic_u32 next = read32_le(code + i + 4);
		if ((insn & 0xFFFF0000) == 0x24020000 && next == 0x0000000c) {
			pic_u32 nr = insn & 0xFFFF;
			pic_u32 lnr = translate_nr(nr);
			if (lnr != nr)
				write32_le(code + i,
					(insn & 0xFFFF0000) | (lnr & 0xFFFF));
		}
	}
}
#endif
static void patch_syscalls(pic_u8 *code, pic_size_t size)
{
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
	patch_syscalls_mips_be(code, size);
#else
	patch_syscalls_mips_le(code, size);
#endif
}
#else
static void patch_syscalls(pic_u8 *code, pic_size_t size)
{
#if defined(__x86_64__)
	patch_syscalls_x86_64(code, size);
#elif defined(__i386__)
	patch_syscalls_i386(code, size);
#elif defined(__aarch64__)
	patch_syscalls_aarch64(code, size);
#elif defined(__arm__)
	patch_syscalls_arm(code, size);
#elif defined(__s390x__)
	patch_syscalls_s390x(code, size);
#endif
}
#endif

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

#if defined(__x86_64__)
#include "start/x86_64.h"
#elif defined(__i386__)
#include "start/i386.h"
#elif defined(__aarch64__)
#include "start/aarch64.h"
#elif defined(__arm__)
#include "start/arm.h"
#elif defined(__s390x__)
#include "start/s390x.h"
#elif defined(__mips__)
#include "start/mips.h"
#else
#error "FreeBSD runner: unsupported architecture for _start"
#endif

/*
 * Parse an unsigned hex/decimal literal from a NUL-terminated string.
 * Accepts "0x"/"0X" prefix for hex. Returns 0 on empty/invalid input.
 */
static int parse_digit(char c, int base)
{
	if (c >= '0' && c <= '9')
		return c - '0';
	if (base == 16 && c >= 'a' && c <= 'f')
		return c - 'a' + 10;
	if (base == 16 && c >= 'A' && c <= 'F')
		return c - 'A' + 10;
	return -1;
}

static pic_size_t parse_size(const char *s)
{
	if (!s || !*s)
		return 0;
	pic_size_t v = 0;
	int base = 10;
	if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
		base = 16;
		s += 2;
	}
	for (; *s; s++) {
		int d = parse_digit(*s, base);
		if (d < 0)
			return 0;
		v = v * (pic_size_t)base + (pic_size_t)d;
	}
	return v;
}

int runner_main(int argc, char **argv)
{
	if (argc < 2)
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

	/* Optional argv[2]: hex text_end — scope syscall patching to the
	 * code region so .rodata/.data/.config can't cause false matches. */
	pic_size_t patch_limit = (pic_size_t)size;
	if (argc >= 3) {
		pic_size_t t_end = parse_size(argv[2]);
		if (t_end > 0 && t_end <= (pic_size_t)size)
			patch_limit = t_end;
	}
	patch_syscalls((pic_u8 *)blob, patch_limit);

#ifdef __thumb__
	((void (*)(void))((pic_uintptr)blob | 1))();
#else
	((void (*)(void))blob)();
#endif
	pic_exit_group(RUNNER_ERROR);
}
