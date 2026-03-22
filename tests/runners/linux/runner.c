/*
 * Linux test runner for PIC blobs.
 *
 * Loads a blob binary into an RWX memory region and transfers
 * execution to offset 0. The blob executes using real Linux
 * syscalls (emulated by QEMU user-static for non-native arches).
 *
 * Usage: ./runner <blob.bin>
 *
 * Exit code is the blob's exit code (or 127 on runner error).
 */

#include "picblobs/sys/linux/nr.h"
#include "picblobs/sys/read.h"
#include "picblobs/sys/open.h"
#include "picblobs/sys/close.h"
#include "picblobs/sys/lseek.h"
#include "picblobs/sys/mmap.h"
#include "picblobs/sys/exit.h"

#define RUNNER_ERROR 127

static long file_size(int fd) {
    long end = pic_lseek(fd, 0, PIC_SEEK_END);
    if (end < 0) return -1;
    pic_lseek(fd, 0, PIC_SEEK_SET);
    return end;
}

static long read_all(int fd, void *buf, pic_size_t count) {
    pic_u8 *p = (pic_u8 *)buf;
    pic_size_t done = 0;
    while (done < count) {
        long n = pic_read(fd, p + done, count - done);
        if (n <= 0) return -1;
        done += (pic_size_t)n;
    }
    return (long)done;
}

/*
 * Per-architecture _start — reads argc/argv from the kernel-provided
 * stack frame and calls runner_main(argc, argv).
 *
 * Uses top-level __asm__ (not naked functions) for portability
 * across all GCC targets.
 */

#if defined(__x86_64__)
__asm__ (
    ".section .text._start,\"ax\"\n"
    ".globl _start\n"
    "_start:\n"
    "  xor %ebp, %ebp\n"
    "  mov (%rsp), %rdi\n"        /* argc */
    "  lea 8(%rsp), %rsi\n"       /* argv */
    "  call runner_main\n"
    "  mov %eax, %edi\n"
    "  mov $231, %eax\n"          /* exit_group */
    "  syscall\n"
);

#elif defined(__i386__)
__asm__ (
    ".section .text._start,\"ax\"\n"
    ".globl _start\n"
    "_start:\n"
    "  xor %ebp, %ebp\n"
    "  mov (%esp), %eax\n"        /* argc */
    "  lea 4(%esp), %ecx\n"       /* argv */
    "  sub $8, %esp\n"            /* align */
    "  push %ecx\n"               /* argv */
    "  push %eax\n"               /* argc */
    "  call runner_main\n"
    "  mov %eax, %ebx\n"
    "  mov $252, %eax\n"          /* exit_group */
    "  int $0x80\n"
);

#elif defined(__aarch64__)
__asm__ (
    ".section .text._start,\"ax\"\n"
    ".globl _start\n"
    "_start:\n"
    "  ldr x0, [sp]\n"            /* argc */
    "  add x1, sp, #8\n"          /* argv */
    "  bl runner_main\n"
    "  mov x8, #94\n"             /* exit_group */
    "  svc #0\n"
);

#elif defined(__arm__)
__asm__ (
    ".section .text._start,\"ax\"\n"
    ".globl _start\n"
    "_start:\n"
    "  ldr r0, [sp]\n"            /* argc */
    "  add r1, sp, #4\n"          /* argv */
    "  bl runner_main\n"
    "  mov r7, #248\n"            /* exit_group */
    "  svc #0\n"
);

#elif defined(__mips__)
__asm__ (
    ".section .text._start,\"ax\"\n"
    ".globl _start\n"
    ".ent _start\n"
    "_start:\n"
    "  .set noreorder\n"
    "  bal 1f\n"                   /* get PC */
    "  nop\n"
    "1: .cpload $ra\n"            /* set $gp from current PC */
    "  lw $a0, 0($sp)\n"          /* argc */
    "  addiu $a1, $sp, 4\n"       /* argv */
    "  addiu $sp, $sp, -32\n"     /* frame (o32 ABI) */
    "  sw $ra, 28($sp)\n"
    "  la $t9, runner_main\n"
    "  jalr $t9\n"
    "  nop\n"
    "  move $a0, $v0\n"           /* exit code */
    "  li $v0, 4246\n"            /* exit_group */
    "  syscall\n"
    "  .set reorder\n"
    ".end _start\n"
);

#else
#error "Unsupported architecture for _start"
#endif

void runner_main(int argc, char **argv) {
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

    void *mem = pic_mmap(
        PIC_NULL, (pic_size_t)size,
        PIC_PROT_READ | PIC_PROT_WRITE | PIC_PROT_EXEC,
        PIC_MAP_PRIVATE | PIC_MAP_ANONYMOUS,
        -1, 0
    );
    if ((long)mem <= 0) {
        pic_close(fd);
        pic_exit_group(RUNNER_ERROR);
    }

    if (read_all(fd, mem, (pic_size_t)size) < 0) {
        pic_close(fd);
        pic_exit_group(RUNNER_ERROR);
    }

    pic_close(fd);

    ((void (*)(void))mem)();

    pic_exit_group(RUNNER_ERROR);
}
