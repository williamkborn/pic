#ifndef PICBLOBS_SYS_CLOSE_H
#define PICBLOBS_SYS_CLOSE_H
#include "picblobs/syscall.h"

static inline long pic_close(int fd) {
    return pic_syscall1(__NR_close, fd);
}

#endif
