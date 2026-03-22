#ifndef PICBLOBS_SYS_EXIT_H
#define PICBLOBS_SYS_EXIT_H
#include "picblobs/syscall.h"

__attribute__((noreturn))
static inline void pic_exit(int code) {
    pic_syscall1(__NR_exit, code);
    __builtin_unreachable();
}

__attribute__((noreturn))
static inline void pic_exit_group(int code) {
    pic_syscall1(__NR_exit_group, code);
    __builtin_unreachable();
}

#endif
