#ifndef PICBLOBS_SYS_READ_H
#define PICBLOBS_SYS_READ_H
#include "picblobs/syscall.h"

static inline long pic_read(int fd, void *buf, pic_size_t count) {
    return pic_syscall3(__NR_read, fd, (long)buf, count);
}

#endif
