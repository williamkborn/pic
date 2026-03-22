#ifndef PICBLOBS_SYS_MMAP_H
#define PICBLOBS_SYS_MMAP_H
#include "picblobs/syscall.h"

static inline void *pic_mmap(void *addr, pic_size_t len, int prot,
                             int flags, int fd, long offset) {
    /*
     * On 32-bit arches using mmap2, the offset is in pages (4096 bytes),
     * not bytes. On 64-bit arches using plain mmap, offset is in bytes.
     */
#if defined(__mips__) || defined(__arm__) || defined(__i386__)
    return (void *)pic_syscall6(__NR_mmap, (long)addr, len, prot, flags, fd, offset >> 12);
#else
    return (void *)pic_syscall6(__NR_mmap, (long)addr, len, prot, flags, fd, offset);
#endif
}

#endif
