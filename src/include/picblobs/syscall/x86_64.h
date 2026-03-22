/* pic_raw_syscall — x86_64 (syscall instruction). */

static inline long pic_raw_syscall(
	long n, long a0, long a1, long a2, long a3, long a4, long a5)
{
	long ret;
	register long r10 __asm__("r10") = a3;
	register long r8 __asm__("r8") = a4;
	register long r9 __asm__("r9") = a5;
	__asm__ volatile("syscall"
		: "=a"(ret)
		: "a"(n), "D"(a0), "S"(a1), "d"(a2), "r"(r10), "r"(r8), "r"(r9)
		: "rcx", "r11", "memory");
	return ret;
}
