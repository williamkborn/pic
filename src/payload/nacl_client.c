/*
 * nacl_client — NaCl symmetric-encrypted TCP client PIC blob.
 *
 * Uses crypto_secretbox (XSalsa20-Poly1305) with a pre-shared key.
 *
 * Protocol:
 *   1. Connects to server at 127.0.0.1:9999.
 *   2. Sends: nonce (24B) + length (4B LE) + ciphertext.
 *   3. Receives encrypted ACK, decrypts and verifies.
 *   4. Exits 0 on success, 1 on failure.
 */

#ifndef PIC_PLATFORM_HOSTED
#include "picblobs/os/linux.h"
#endif
#include "picblobs/log.h"
#include "picblobs/mem.h"
#include "picblobs/net.h"
#include "picblobs/reloc.h"
#include "picblobs/section.h"
#include "picblobs/sys/exit_group.h"
#include "picblobs/sys/write.h"
#include "picblobs/sys/read.h"
#include "picblobs/sys/close.h"
#include "picblobs/sys/socket.h"
#include "picblobs/sys/connect.h"
#include "picblobs/crypto/randombytes.h"
#include "picblobs/crypto/tweetnacl.h"

#define SERVER_PORT 9999
#define MAX_CT 4096

/* Same pre-shared key as server. */
PIC_RODATA
static const unsigned char PSK[32] = {
	0x4a, 0x6f, 0x68, 0x6e, 0x20, 0x44, 0x6f, 0x65,
	0x2d, 0x50, 0x49, 0x43, 0x2d, 0x4e, 0x61, 0x43,
	0x6c, 0x2d, 0x50, 0x53, 0x4b, 0x2d, 0x30, 0x30,
	0x31, 0x21, 0x21, 0x21, 0x00, 0x00, 0x00, 0x00,
};

PIC_RODATA static const char tag_send[] = "[client] sending encrypted message\n";
PIC_RODATA static const char tag_ack[]  = "[client] decrypted ACK: ";
PIC_RODATA static const char tag_ok[]   = "[client] secure channel OK\n";
PIC_RODATA static const char tag_fail[] = "[client] FAILED\n";
PIC_RODATA static const char newline[]  = "\n";
PIC_RODATA static const char message[]  = "Hello from NaCl PIC blob!";
PIC_RODATA static const char server_ip[] = "127.0.0.1";

PIC_TEXT
static int read_exact(int fd, void *buf, pic_size_t n)
{
	pic_u8 *p = (pic_u8 *)buf;
	pic_size_t done = 0;
	while (done < n) {
		long r = pic_read(fd, p + done, n - done);
		if (r <= 0) return -1;
		done += (pic_size_t)r;
	}
	return 0;
}

PIC_TEXT
static int write_all(int fd, const void *buf, pic_size_t n)
{
	const pic_u8 *p = (const pic_u8 *)buf;
	pic_size_t done = 0;
	while (done < n) {
		long r = pic_write(fd, p + done, n - done);
		if (r <= 0) return -1;
		done += (pic_size_t)r;
	}
	return 0;
}

PIC_TEXT
static pic_u32 parse_ipv4(const char *s)
{
	pic_u32 octets[4] = {0, 0, 0, 0};
	int idx = 0;
	while (*s && idx < 4) {
		if (*s == '.') { idx++; s++; continue; }
		octets[idx] = octets[idx] * 10 + (pic_u32)(*s - '0');
		s++;
	}
	return octets[0] | (octets[1] << 8) | (octets[2] << 16) | (octets[3] << 24);
}

PIC_TEXT
static long recv_decrypt(int fd, const unsigned char *key,
			 unsigned char *pt, pic_size_t pt_cap)
{
	unsigned char nonce[crypto_secretbox_NONCEBYTES];
	unsigned char ct[crypto_secretbox_ZEROBYTES + MAX_CT];
	pic_u8 len_buf[4];
	pic_u32 ct_len;
	pic_u64 box_len;

	if (read_exact(fd, nonce, sizeof(nonce)) < 0) return -1;
	if (read_exact(fd, len_buf, 4) < 0) return -1;

	ct_len = (pic_u32)len_buf[0] | ((pic_u32)len_buf[1] << 8) |
		 ((pic_u32)len_buf[2] << 16) | ((pic_u32)len_buf[3] << 24);
	if (ct_len > MAX_CT) return -1;

	pic_memset(ct, 0, crypto_secretbox_BOXZEROBYTES);
	if (read_exact(fd, ct + crypto_secretbox_BOXZEROBYTES, ct_len) < 0)
		return -1;

	box_len = (pic_u64)ct_len + crypto_secretbox_BOXZEROBYTES;
	if (box_len > pt_cap) return -1;

	if (crypto_secretbox_open(pt, ct, box_len, nonce, key) != 0)
		return -1;

	return (long)(box_len - crypto_secretbox_ZEROBYTES);
}

PIC_TEXT
static int encrypt_send(int fd, const unsigned char *key,
			const void *msg, pic_size_t msg_len)
{
	unsigned char nonce[crypto_secretbox_NONCEBYTES];
	unsigned char pt[crypto_secretbox_ZEROBYTES + MAX_CT];
	unsigned char ct[crypto_secretbox_ZEROBYTES + MAX_CT];
	pic_u64 box_len = crypto_secretbox_ZEROBYTES + msg_len;
	pic_u32 ct_len;
	pic_u8 len_buf[4];

	if (msg_len > MAX_CT) return -1;

	randombytes(nonce, sizeof(nonce));
	pic_memset(pt, 0, crypto_secretbox_ZEROBYTES);
	pic_memcpy(pt + crypto_secretbox_ZEROBYTES, msg, msg_len);

	crypto_secretbox(ct, pt, box_len, nonce, key);

	ct_len = (pic_u32)(box_len - crypto_secretbox_BOXZEROBYTES);
	len_buf[0] = (pic_u8)(ct_len);
	len_buf[1] = (pic_u8)(ct_len >> 8);
	len_buf[2] = (pic_u8)(ct_len >> 16);
	len_buf[3] = (pic_u8)(ct_len >> 24);

	if (write_all(fd, nonce, sizeof(nonce)) < 0) return -1;
	if (write_all(fd, len_buf, 4) < 0) return -1;
	if (write_all(fd, ct + crypto_secretbox_BOXZEROBYTES, ct_len) < 0)
		return -1;
	return 0;
}

PIC_ENTRY
void _start(
#ifdef PIC_PLATFORM_HOSTED
	const struct pic_platform *plat
#else
	void
#endif
)
{
	PIC_SELF_RELOCATE();
#ifdef PIC_PLATFORM_HOSTED
	PIC_PLATFORM_INIT(plat);
#endif

	unsigned char pt[crypto_secretbox_ZEROBYTES + MAX_CT];
	int sock;
	long ret, pt_len;

	sock = (int)pic_socket(PIC_AF_INET, PIC_SOCK_STREAM, 0);
	if (sock < 0) pic_exit_group(1);

	struct pic_sockaddr_in addr;
	pic_memset(&addr, 0, sizeof(addr));
	addr.sin_family = PIC_AF_INET;
	addr.sin_port = pic_htons(SERVER_PORT);
	addr.sin_addr = parse_ipv4(server_ip);

	/* Retry connect — server may need time to start. */
	int attempts = 50;
	while (attempts > 0) {
		ret = pic_connect(sock, &addr, sizeof(addr));
		if (ret >= 0) break;
		for (volatile int i = 0; i < 1000000; i++) ;
		attempts--;
		if (attempts > 0) {
			pic_close(sock);
			sock = (int)pic_socket(PIC_AF_INET, PIC_SOCK_STREAM, 0);
			if (sock < 0) pic_exit_group(1);
		}
	}
	if (ret < 0) goto fail;

	/* Send encrypted message. */
	pic_write(1, tag_send, sizeof(tag_send) - 1);
	if (encrypt_send(sock, PSK, message, sizeof(message) - 1) < 0)
		goto fail;

	/* Receive encrypted ACK. */
	pt_len = recv_decrypt(sock, PSK, pt, sizeof(pt));
	if (pt_len < 0) goto fail;

	pic_write(1, tag_ack, sizeof(tag_ack) - 1);
	pic_write(1, pt + crypto_secretbox_ZEROBYTES, (pic_size_t)pt_len);
	pic_write(1, newline, 1);

	pic_write(1, tag_ok, sizeof(tag_ok) - 1);
	pic_close(sock);
	pic_exit_group(0);

fail:
	pic_write(2, tag_fail, sizeof(tag_fail) - 1);
	pic_close(sock);
	pic_exit_group(1);
}
