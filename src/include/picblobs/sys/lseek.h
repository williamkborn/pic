#ifndef PICBLOBS_SYS_LSEEK_H
#define PICBLOBS_SYS_LSEEK_H
#include "picblobs/syscall.h"

static inline long pic_lseek(int fd, long offset, int whence) {
    return pic_syscall3(__NR_lseek, fd, offset, whence);
}

#endif
