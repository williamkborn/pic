/*
 * FreeBSD test runner for PIC blobs (test-mode shim).
 *
 * This runner tests FreeBSD blobs compiled in test-mode, where the
 * bottom-level syscall handler jumps to a fixed shim address instead
 * of executing a real FreeBSD syscall instruction.
 *
 * The shim (placed at a fixed address by a test-specific linker script):
 *   1. Receives the FreeBSD syscall number and up to 6 arguments.
 *   2. Logs the call to a verification buffer.
 *   3. Validates the syscall number matches FreeBSD conventions.
 *   4. Returns canned success values.
 *
 * After blob execution, the runner inspects the verification buffer
 * and reports results.
 *
 * Usage: ./runner <blob.bin>
 */

#include "picblobs/types.h"
#include "picblobs/sys/linux/nr.h"
#include "picblobs/syscall.h"
#include "picblobs/sys/exit.h"

#define RUNNER_ERROR 127
#define MAX_SYSCALL_LOG 256

/* Verification log entry. */
struct syscall_record {
    long number;
    long args[6];
};

/* Verification buffer — filled by the shim, read by the runner. */
static struct syscall_record syscall_log[MAX_SYSCALL_LOG];
static int syscall_log_count = 0;

/*
 * Shim entry point — this function will be placed at the fixed shim
 * address by the test-mode linker script. The blob's syscall dispatch
 * jumps here instead of executing a real syscall instruction.
 *
 * The calling convention matches the architecture's syscall convention:
 * syscall number in the standard register, args in subsequent registers.
 */
long __attribute__((section(".shim")))
freebsd_syscall_shim(long number, long a0, long a1, long a2,
                     long a3, long a4, long a5) {
    if (syscall_log_count < MAX_SYSCALL_LOG) {
        struct syscall_record *rec = &syscall_log[syscall_log_count++];
        rec->number = number;
        rec->args[0] = a0;
        rec->args[1] = a1;
        rec->args[2] = a2;
        rec->args[3] = a3;
        rec->args[4] = a4;
        rec->args[5] = a5;
    }

    /* Return canned success value. */
    /* TODO: per-syscall return value table for FreeBSD. */
    return 0;
}

void runner_main(int argc, char **argv) {
    if (argc < 2) {
        pic_exit_group(RUNNER_ERROR);
    }

    /* TODO: load blob, execute, then inspect syscall_log. */

    /* Report results via exit code. */
    int result = (syscall_log_count > 0) ? 0 : 1;
    pic_exit_group(result);
}
