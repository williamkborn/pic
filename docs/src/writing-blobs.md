# Writing a Blob

A blob is a freestanding C program that runs at any address. Include the
target OS header first, then the syscall wrappers you need.

## Linux blob

```c
#include "picblobs/os/linux.h"
#include "picblobs/section.h"
#include "picblobs/reloc.h"
#include "picblobs/sys/write.h"
#include "picblobs/sys/exit_group.h"

PIC_RODATA
static const char msg[] = "Hello, world!\n";

PIC_ENTRY
void _start(void)
{
    PIC_SELF_RELOCATE();
    pic_write(1, msg, sizeof(msg) - 1);
    pic_exit_group(0);
}
```

## Windows blob

```c
#include "picblobs/os/windows.h"
#include "picblobs/section.h"
#include "picblobs/reloc.h"
#include "picblobs/win/resolve.h"

/* DJB2 hashes of API function names */
#define HASH_KERNEL32       0x7040EE75
#define HASH_GetStdHandle   0xF178843C
#define HASH_WriteFile      0x663CECB0
#define HASH_ExitProcess    0xB769339E

PIC_RODATA
static const char msg[] = "Hello, world!\n";

PIC_ENTRY
void _start(void)
{
    PIC_SELF_RELOCATE();
    void *k32 = pic_resolve_module(HASH_KERNEL32);
    void *(*GetStdHandle)(unsigned long) = pic_resolve_export(k32, HASH_GetStdHandle);
    // ... resolve and call APIs
}
```

## Key conventions

- Each `sys/*.h` header is a self-contained module with syscall numbers for every OS/architecture combination, constants, and wrapper function.
- Use `PIC_RODATA` for read-only data (ensures correct section placement in freestanding PIC).
- Use `PIC_ENTRY` for the entry point and `PIC_SELF_RELOCATE()` at the top for MIPS GOT relocation.
- Drop a `.c` file into `src/payload/`, run `python tools/generate.py`, and it will be picked up automatically.
