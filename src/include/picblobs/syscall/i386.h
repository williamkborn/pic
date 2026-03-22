/*
 * pic_raw_syscall — i386 (int 0x80).
 *
 * Linux i386 ABI: ebx=a0, ecx=a1, edx=a2, esi=a3, edi=a4, ebp=a5.
 */

static inline long pic_raw_syscall(
	long n, long a0, long a1, long a2, long a3, long a4, long a5)
{
	long ret;
	__asm__ volatile("push %%ebp\n\t"
			 "push %%edi\n\t"
			 "mov %[a4], %%edi\n\t"
			 "mov %[a5], %%ebp\n\t"
			 "int $0x80\n\t"
			 "pop %%edi\n\t"
			 "pop %%ebp"
		: "=a"(ret)
		: "a"(n), "b"(a0), "c"(a1), "d"(a2),
		"S"(a3), [a4] "m"(a4), [a5] "m"(a5)
		: "memory");
	return ret;
}
