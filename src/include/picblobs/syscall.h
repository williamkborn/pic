/*
 * picblobs/syscall.h — architecture-portable syscall interface.
 *
 * Provides pic_syscall0..pic_syscall6 functions that invoke the
 * single-instruction syscall primitive defined per architecture
 * in assembly (REQ-001, ADR-006).
 *
 * Syscall numbers are defined per OS/architecture in separate
 * headers (syscall_numbers_linux.h, syscall_numbers_freebsd.h).
 *
 * This header is the only interface between C code and the kernel.
 */

#ifndef PICBLOBS_SYSCALL_H
#define PICBLOBS_SYSCALL_H

#include "picblobs/types.h"

/*
 * The raw syscall primitive is implemented in assembly per architecture.
 * It takes the syscall number and up to 6 arguments in registers and
 * returns the result.
 *
 * Signature: long pic_raw_syscall(long number, long a0..a5)
 *
 * For now, provide inline-assembly implementations for supported
 * architectures. The final implementation will use separate .S files
 * per ADR-006.
 */

#if defined(__x86_64__)

static inline long pic_raw_syscall(long n, long a0, long a1, long a2,
                                   long a3, long a4, long a5) {
    long ret;
    register long r10 __asm__("r10") = a3;
    register long r8  __asm__("r8")  = a4;
    register long r9  __asm__("r9")  = a5;
    __asm__ volatile (
        "syscall"
        : "=a"(ret)
        : "a"(n), "D"(a0), "S"(a1), "d"(a2),
          "r"(r10), "r"(r8), "r"(r9)
        : "rcx", "r11", "memory"
    );
    return ret;
}

#elif defined(__i386__)

static inline long pic_raw_syscall(long n, long a0, long a1, long a2,
                                   long a3, long a4, long a5) {
    long ret;
    __asm__ volatile (
        "push %%ebp\n\t"
        "mov %[a4], %%ebp\n\t"
        "int $0x80\n\t"
        "pop %%ebp"
        : "=a"(ret)
        : "a"(n), "b"(a0), "c"(a1), "d"(a2), "S"(a3),
          [a4] "m"(a4)
        : "memory"
    );
    (void)a5;
    return ret;
}

#elif defined(__aarch64__)

static inline long pic_raw_syscall(long n, long a0, long a1, long a2,
                                   long a3, long a4, long a5) {
    register long x8  __asm__("x8")  = n;
    register long x0  __asm__("x0")  = a0;
    register long x1  __asm__("x1")  = a1;
    register long x2  __asm__("x2")  = a2;
    register long x3  __asm__("x3")  = a3;
    register long x4  __asm__("x4")  = a4;
    register long x5  __asm__("x5")  = a5;
    __asm__ volatile (
        "svc #0"
        : "=r"(x0)
        : "r"(x8), "r"(x0), "r"(x1), "r"(x2),
          "r"(x3), "r"(x4), "r"(x5)
        : "memory"
    );
    return x0;
}

#elif defined(__arm__)

static inline long pic_raw_syscall(long n, long a0, long a1, long a2,
                                   long a3, long a4, long a5) {
    register long r7  __asm__("r7")  = n;
    register long r0  __asm__("r0")  = a0;
    register long r1  __asm__("r1")  = a1;
    register long r2  __asm__("r2")  = a2;
    register long r3  __asm__("r3")  = a3;
    register long r4  __asm__("r4")  = a4;
    register long r5  __asm__("r5")  = a5;
    __asm__ volatile (
        "svc #0"
        : "=r"(r0)
        : "r"(r7), "r"(r0), "r"(r1), "r"(r2),
          "r"(r3), "r"(r4), "r"(r5)
        : "memory"
    );
    return r0;
}

#elif defined(__mips__)

/*
 * MIPS o32 ABI: $a0-$a3 ($4-$7) carry the first 4 args, args 5-6
 * go on the stack at sp+16 and sp+20 (the caller must reserve a
 * 4-word argument save area at sp+0..sp+15 even for reg args).
 * Syscall number goes in $v0 ($2).
 */
static inline long pic_raw_syscall(long n, long a0, long a1, long a2,
                                   long a3, long a4, long a5) {
    register long v0 __asm__("$2")  = n;
    register long r4 __asm__("$4")  = a0;
    register long r5 __asm__("$5")  = a1;
    register long r6 __asm__("$6")  = a2;
    register long r7 __asm__("$7")  = a3;
    /*
     * MIPS o32 syscall: kernel reads args 5-6 from the caller's
     * stack at sp+16 and sp+20. We allocate a new frame so our
     * stores don't clobber the caller's local variables.
     */
    __asm__ volatile (
        ".set noreorder\n\t"
        "addiu $sp, $sp, -32\n\t"   /* new frame */
        "sw    %[arg5], 16($sp)\n\t"
        "sw    %[arg6], 20($sp)\n\t"
        "syscall\n\t"
        "addiu $sp, $sp, 32\n\t"    /* restore */
        ".set reorder\n\t"
        : "+r"(v0)
        : "r"(r4), "r"(r5), "r"(r6), "r"(r7),
          [arg5] "r"(a4), [arg6] "r"(a5)
        : "memory", "$3", "$8", "$9", "$10", "$11",
          "$12", "$13", "$14", "$15", "$24", "$25"
    );
    return v0;
}

#else
#error "Unsupported architecture for pic_raw_syscall"
#endif

/* Convenience wrappers. */
#define pic_syscall0(n)                     pic_raw_syscall((n), 0, 0, 0, 0, 0, 0)
#define pic_syscall1(n, a)                  pic_raw_syscall((n), (long)(a), 0, 0, 0, 0, 0)
#define pic_syscall2(n, a, b)               pic_raw_syscall((n), (long)(a), (long)(b), 0, 0, 0, 0)
#define pic_syscall3(n, a, b, c)            pic_raw_syscall((n), (long)(a), (long)(b), (long)(c), 0, 0, 0)
#define pic_syscall4(n, a, b, c, d)         pic_raw_syscall((n), (long)(a), (long)(b), (long)(c), (long)(d), 0, 0)
#define pic_syscall5(n, a, b, c, d, e)      pic_raw_syscall((n), (long)(a), (long)(b), (long)(c), (long)(d), (long)(e), 0)
#define pic_syscall6(n, a, b, c, d, e, f)   pic_raw_syscall((n), (long)(a), (long)(b), (long)(c), (long)(d), (long)(e), (long)(f))

/*
 * Syscall numbers and constants are in per-OS headers:
 *   picblobs/sys/linux/nr.h
 *   picblobs/sys/freebsd/nr.h
 */

#endif /* PICBLOBS_SYSCALL_H */
