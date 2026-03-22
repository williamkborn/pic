#ifndef PICBLOBS_SYS_MUNMAP_H
#define PICBLOBS_SYS_MUNMAP_H
#include "picblobs/syscall.h"

static inline long pic_munmap(void *addr, pic_size_t len) {
    return pic_syscall2(__NR_munmap, (long)addr, len);
}

#endif
