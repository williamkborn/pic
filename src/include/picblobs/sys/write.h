#ifndef PICBLOBS_SYS_WRITE_H
#define PICBLOBS_SYS_WRITE_H
#include "picblobs/syscall.h"

static inline long pic_write(int fd, const void *buf, pic_size_t count) {
    return pic_syscall3(__NR_write, fd, (long)buf, count);
}

#endif
