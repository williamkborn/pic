#ifndef PICBLOBS_SYS_MPROTECT_H
#define PICBLOBS_SYS_MPROTECT_H
#include "picblobs/syscall.h"

static inline long pic_mprotect(void *addr, pic_size_t len, int prot) {
    return pic_syscall3(__NR_mprotect, (long)addr, len, prot);
}

#endif
