/*
 * picblobs/sys/freebsd/nr.h — FreeBSD syscall numbers.
 *
 * FreeBSD syscall numbers are architecture-independent.
 * TODO: generate from FreeBSD headers per REQ-004.
 */

#ifndef PICBLOBS_SYS_FREEBSD_NR_H
#define PICBLOBS_SYS_FREEBSD_NR_H

#define __NR_read           3
#define __NR_write          4
#define __NR_open           5
#define __NR_close          6
#define __NR_lseek          478
#define __NR_mmap           477
#define __NR_mprotect       74
#define __NR_munmap         73
#define __NR_exit           1
#define __NR_exit_group     431  /* sys_exit_group */
#define __NR_socket         97
#define __NR_connect        98

/* mmap prot flags — same as Linux */
#define PIC_PROT_NONE    0x0
#define PIC_PROT_READ    0x1
#define PIC_PROT_WRITE   0x2
#define PIC_PROT_EXEC    0x4

/* mmap flags */
#define PIC_MAP_SHARED    0x0001
#define PIC_MAP_PRIVATE   0x0002
#define PIC_MAP_FIXED     0x0010
#define PIC_MAP_ANONYMOUS 0x1000  /* different from Linux! */

/* lseek whence */
#define PIC_SEEK_SET 0
#define PIC_SEEK_CUR 1
#define PIC_SEEK_END 2

/* open flags */
#define PIC_O_RDONLY 0
#define PIC_O_WRONLY 1
#define PIC_O_RDWR   2

#endif /* PICBLOBS_SYS_FREEBSD_NR_H */
