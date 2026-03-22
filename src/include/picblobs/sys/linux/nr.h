/*
 * picblobs/sys/linux/nr.h — Linux syscall numbers.
 *
 * Per-architecture syscall number tables. Include this before
 * any wrapper headers under picblobs/sys/.
 *
 * TODO: generate from kernel headers per REQ-004.
 * Currently: x86_64 only, manually maintained.
 */

#ifndef PICBLOBS_SYS_LINUX_NR_H
#define PICBLOBS_SYS_LINUX_NR_H

#if defined(__x86_64__)

#define __NR_read           0
#define __NR_write          1
#define __NR_open           2
#define __NR_close          3
#define __NR_fstat          5
#define __NR_lseek          8
#define __NR_mmap           9
#define __NR_mprotect       10
#define __NR_munmap         11
#define __NR_socket         41
#define __NR_connect        42
#define __NR_accept         43
#define __NR_bind           49
#define __NR_listen         50
#define __NR_setsockopt     54
#define __NR_dup2           33
#define __NR_pipe           22
#define __NR_exit           60
#define __NR_exit_group     231

#elif defined(__i386__)

#define __NR_read           3
#define __NR_write          4
#define __NR_open           5
#define __NR_close          6
#define __NR_lseek          19
#define __NR_mmap           192  /* mmap2 */
#define __NR_mprotect       125
#define __NR_munmap         91
#define __NR_exit           1
#define __NR_exit_group     252
#define __NR_socket         359
#define __NR_connect        362

#elif defined(__aarch64__)

#define __NR_read           63
#define __NR_write          64
#define __NR_openat         56
/* aarch64 has no legacy __NR_open — use pic_open() which calls openat */
#define __NR_close          57
#define __NR_lseek          62
#define __NR_mmap           222
#define __NR_mprotect       226
#define __NR_munmap         215
#define __NR_exit           93
#define __NR_exit_group     94
#define __NR_socket         198
#define __NR_connect        203

#elif defined(__arm__)

#define __NR_read           3
#define __NR_write          4
#define __NR_open           5
#define __NR_close          6
#define __NR_lseek          19
#define __NR_mmap           192  /* mmap2 */
#define __NR_mprotect       125
#define __NR_munmap         91
#define __NR_exit           1
#define __NR_exit_group     248
#define __NR_socket         281
#define __NR_connect        283

#elif defined(__mips__)

#define __NR_read           4003
#define __NR_write          4004
#define __NR_open           4005
#define __NR_close          4006
#define __NR_lseek          4019
#define __NR_mmap           4210  /* mmap2: offset in pages, not bytes */
#define __NR_mprotect       4125
#define __NR_munmap         4091
#define __NR_exit           4001
#define __NR_exit_group     4246
#define __NR_socket         4183
#define __NR_connect        4170

#else
#error "Unsupported architecture for Linux syscall numbers"
#endif

/* mmap prot flags */
#define PIC_PROT_NONE    0x0
#define PIC_PROT_READ    0x1
#define PIC_PROT_WRITE   0x2
#define PIC_PROT_EXEC    0x4

/* mmap flags — MIPS uses different values! */
#if defined(__mips__)
#define PIC_MAP_SHARED    0x001
#define PIC_MAP_PRIVATE   0x002
#define PIC_MAP_FIXED     0x010
#define PIC_MAP_ANONYMOUS 0x800
#else
#define PIC_MAP_SHARED    0x01
#define PIC_MAP_PRIVATE   0x02
#define PIC_MAP_FIXED     0x10
#define PIC_MAP_ANONYMOUS 0x20
#endif

/* lseek whence */
#define PIC_SEEK_SET 0
#define PIC_SEEK_CUR 1
#define PIC_SEEK_END 2

/* open flags */
#define PIC_O_RDONLY 0
#define PIC_O_WRONLY 1
#define PIC_O_RDWR   2

#endif /* PICBLOBS_SYS_LINUX_NR_H */
