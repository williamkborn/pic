/* picblobs/cache.h — instruction-cache synchronization helpers. */

#ifndef PICBLOBS_CACHE_H
#define PICBLOBS_CACHE_H

#include "picblobs/types.h"

static inline void pic_sync_icache(void *addr, pic_size_t len)
{
	if (len == 0)
		return;
#if defined(__riscv)
	(void)addr;
	__asm__ volatile("fence.i" ::: "memory");
#else
	__builtin___clear_cache((char *)addr, (char *)addr + len);
#endif
}

#endif /* PICBLOBS_CACHE_H */
