#ifndef PICBLOBS_SYS_OPEN_H
#define PICBLOBS_SYS_OPEN_H
#include "picblobs/syscall.h"

#ifndef AT_FDCWD
#define AT_FDCWD -100
#endif

static inline long pic_open(const char *path, int flags, int mode) {
#ifdef __NR_openat
    /* aarch64 and other new-style arches only have openat, not open. */
    return pic_syscall4(__NR_openat, AT_FDCWD, (long)path, flags, mode);
#else
    return pic_syscall3(__NR_open, (long)path, flags, mode);
#endif
}

#endif
