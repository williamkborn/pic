/*
 * "Hello, world!" payload — minimal freestanding PIC blob.
 *
 * Uses PIC_RODATA on all architectures. On MIPS, PIC_SELF_RELOCATE()
 * patches the GOT so rodata references work at any load address.
 */

#include "picblobs/os/linux.h"
#include "picblobs/reloc.h"
#include "picblobs/section.h"
#include "picblobs/sys/exit.h"
#include "picblobs/sys/exit_group.h"
#include "picblobs/sys/write.h"

PIC_RODATA
static const char msg[] = "Hello, world!\n";

PIC_ENTRY
void _start(void)
{
	PIC_SELF_RELOCATE();
	pic_write(1, msg, sizeof(msg) - 1);
	pic_exit_group(0);
}
