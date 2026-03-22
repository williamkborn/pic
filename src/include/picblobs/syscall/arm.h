/* pic_raw_syscall — ARM (svc #0). */

static inline long pic_raw_syscall(
	long n, long a0, long a1, long a2, long a3, long a4, long a5)
{
	register long r7 __asm__("r7") = n;
	register long r0 __asm__("r0") = a0;
	register long r1 __asm__("r1") = a1;
	register long r2 __asm__("r2") = a2;
	register long r3 __asm__("r3") = a3;
	register long r4 __asm__("r4") = a4;
	register long r5 __asm__("r5") = a5;
	__asm__ volatile("svc #0"
		: "=r"(r0)
		: "r"(r7), "r"(r0), "r"(r1), "r"(r2), "r"(r3), "r"(r4), "r"(r5)
		: "memory");
	return r0;
}
