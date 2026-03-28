/*
 * Windows test runner — mock TEB/PEB environment.
 *
 * This runner is a Linux binary that constructs a synthetic Windows
 * environment (fake TEB, PEB, module list, export tables) and then
 * executes a Windows-targeting blob within it.
 *
 * The mock environment:
 *   - TEB at a known address with PEB pointer at offset 0x60
 *   - PEB with PEB_LDR_DATA at offset 0x18
 *   - Mock module entries for kernel32.dll, ntdll.dll, ws2_32.dll
 *   - Mock export tables with DJB2-matched function names
 *   - Mock API implementations (VirtualAlloc → mmap, etc.)
 *
 * After execution, the runner inspects a verification log to confirm
 * the blob resolved correct DJB2 hashes and called expected APIs.
 *
 * Usage: ./runner <blob.bin>
 */

#include "picblobs/os/linux.h"
#include "picblobs/sys/exit.h"
#include "picblobs/sys/exit_group.h"
#include "picblobs/sys/mmap.h"
#include "picblobs/sys/mprotect.h"
#include "picblobs/syscall.h"
#include "picblobs/types.h"

#define RUNNER_ERROR 127
#define MAX_API_LOG 256

/* Verification log entry for mock API calls. */
struct api_record {
	unsigned long hash; /* DJB2 hash of the resolved function */
	long args[4];	    /* First 4 arguments */
};

static struct api_record api_log[MAX_API_LOG];
static int api_log_count = 0;

/* ----------------------------------------------------------------
 * Mock Windows structures (minimal, matching blob expectations)
 * ---------------------------------------------------------------- */

/* Mock TEB — only the PEB pointer at offset 0x60 matters. */
struct mock_teb {
	char padding[0x60];
	void *peb;
};

/* Mock PEB — PEB_LDR_DATA pointer at offset 0x18. */
struct mock_peb {
	char padding[0x18];
	void *ldr;
};

/* Mock PEB_LDR_DATA — InMemoryOrderModuleList at offset 0x20. */
struct mock_ldr_data {
	char padding[0x20];
	struct mock_list_entry *module_list_head;
};

/* Doubly-linked list entry (simplified). */
struct mock_list_entry {
	struct mock_list_entry *flink;
	struct mock_list_entry *blink;
};

/* ----------------------------------------------------------------
 * Mock API implementations
 * ---------------------------------------------------------------- */

/*
 * Mock VirtualAlloc — uses Linux mmap to provide real memory.
 * Records the call and returns a valid pointer.
 */
static void *mock_virtual_alloc(
	void *addr, pic_size_t size, unsigned long type, unsigned long protect)
{
	(void)addr;
	(void)type;
	(void)protect;

	/* mmap(NULL, size, PROT_READ|PROT_WRITE|PROT_EXEC,
	 * MAP_PRIVATE|MAP_ANONYMOUS, -1, 0) */
	return pic_mmap(PIC_NULL, size,
		PIC_PROT_READ | PIC_PROT_WRITE | PIC_PROT_EXEC,
		PIC_MAP_PRIVATE | PIC_MAP_ANONYMOUS, -1, 0);
}

/*
 * Mock ExitProcess — calls Linux exit_group.
 */
static void mock_exit_process(unsigned int exit_code)
{
	pic_exit_group((int)exit_code);
}

/* ----------------------------------------------------------------
 * Runner entry
 * ---------------------------------------------------------------- */

void runner_main(int argc, char **argv)
{
	if (argc < 2) {
		pic_exit_group(RUNNER_ERROR);
	}

	/*
	 * TODO: full implementation:
	 * 1. Allocate and populate mock TEB/PEB/LDR structures.
	 * 2. Set up mock module entries with DJB2-hashed export tables.
	 * 3. Set architecture-specific TEB register (gs for x86_64, x18 for
	 * aarch64).
	 * 4. Load the blob binary.
	 * 5. Transfer execution to the blob.
	 * 6. Inspect api_log for verification.
	 */

	(void)mock_virtual_alloc;
	(void)mock_exit_process;
	(void)api_log;
	(void)api_log_count;

	pic_exit_group(RUNNER_ERROR);
}
