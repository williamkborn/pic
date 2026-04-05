/*
 * nacl_server — NaCl symmetric-encrypted TCP server PIC blob.
 *
 * Uses crypto_secretbox (XSalsa20-Poly1305) with a pre-shared key.
 *
 * Protocol:
 *   1. Server binds to 0.0.0.0:9999, accepts one connection.
 *   2. Receives: nonce (24B) + length (4B LE) + ciphertext.
 *   3. Decrypts with crypto_secretbox_open, prints plaintext.
 *   4. Sends encrypted ACK: nonce (24B) + length (4B LE) + ciphertext.
 *   5. Exits 0 on success, 1 on failure.
 */

#ifndef PIC_PLATFORM_HOSTED
#include "picblobs/os/linux.h"
#endif
#include "picblobs/crypto/randombytes.h"
#include "picblobs/crypto/tweetnacl.h"
#include "picblobs/log.h"
#include "picblobs/mem.h"
#include "picblobs/net.h"
#include "picblobs/reloc.h"
#include "picblobs/section.h"
#include "picblobs/sys/accept.h"
#include "picblobs/sys/bind.h"
#include "picblobs/sys/close.h"
#include "picblobs/sys/exit_group.h"
#include "picblobs/sys/listen.h"
#include "picblobs/sys/read.h"
#include "picblobs/sys/setsockopt.h"
#include "picblobs/sys/socket.h"
#include "picblobs/sys/write.h"

#define LISTEN_PORT 9999
#define MAX_CT 4096

/*
 * Pre-shared 32-byte key. Both server and client use the same key.
 * In a real deployment this would come from the config section.
 */
PIC_RODATA
static const unsigned char PSK[32] = {
	0x4a,
	0x6f,
	0x68,
	0x6e,
	0x20,
	0x44,
	0x6f,
	0x65,
	0x2d,
	0x50,
	0x49,
	0x43,
	0x2d,
	0x4e,
	0x61,
	0x43,
	0x6c,
	0x2d,
	0x50,
	0x53,
	0x4b,
	0x2d,
	0x30,
	0x30,
	0x31,
	0x21,
	0x21,
	0x21,
	0x00,
	0x00,
	0x00,
	0x00,
};

PIC_RODATA static const char tag_listen[] = "[server] listening on :9999\n";
PIC_RODATA static const char tag_conn[] = "[server] accepted connection\n";
PIC_RODATA static const char tag_recv[] = "[server] decrypted: ";
PIC_RODATA static const char tag_ok[] = "[server] secure channel OK\n";
PIC_RODATA static const char tag_fail[] = "[server] FAILED\n";
PIC_RODATA static const char newline[] = "\n";
PIC_RODATA static const char ack_msg[] = "OK";

PIC_TEXT
static int read_exact(int fd, void *buf, pic_size_t n)
{
	pic_u8 *p = (pic_u8 *)buf;
	pic_size_t done = 0;
	while (done < n) {
		long r = pic_read(fd, p + done, n - done);
		if (r <= 0)
			return -1;
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
		if (r <= 0)
			return -1;
		done += (pic_size_t)r;
	}
	return 0;
}

/* Read a framed message: nonce(24) + len(4 LE) + ciphertext(len).
 * Returns plaintext length on success, -1 on failure.
 * Plaintext is in pt + crypto_secretbox_ZEROBYTES. */
PIC_TEXT
static long recv_decrypt(
	int fd, const unsigned char *key, unsigned char *pt, pic_size_t pt_cap)
{
	unsigned char nonce[crypto_secretbox_NONCEBYTES];
	unsigned char ct[crypto_secretbox_ZEROBYTES + MAX_CT];
	pic_u8 len_buf[4];
	pic_u32 ct_len;
	pic_u64 box_len;

	if (read_exact(fd, nonce, sizeof(nonce)) < 0)
		return -1;
	if (read_exact(fd, len_buf, 4) < 0)
		return -1;

	ct_len = (pic_u32)len_buf[0] | ((pic_u32)len_buf[1] << 8) |
		((pic_u32)len_buf[2] << 16) | ((pic_u32)len_buf[3] << 24);
	if (ct_len > MAX_CT)
		return -1;

	pic_memset(ct, 0, crypto_secretbox_BOXZEROBYTES);
	if (read_exact(fd, ct + crypto_secretbox_BOXZEROBYTES, ct_len) < 0)
		return -1;

	box_len = (pic_u64)ct_len + crypto_secretbox_BOXZEROBYTES;
	if (box_len > pt_cap)
		return -1;

	if (crypto_secretbox_open(pt, ct, box_len, nonce, key) != 0)
		return -1;

	return (long)(box_len - crypto_secretbox_ZEROBYTES);
}

/* Encrypt and send a framed message: nonce(24) + len(4 LE) + ciphertext. */
PIC_TEXT
static int encrypt_send(
	int fd, const unsigned char *key, const void *msg, pic_size_t msg_len)
{
	unsigned char nonce[crypto_secretbox_NONCEBYTES];
	unsigned char pt[crypto_secretbox_ZEROBYTES + MAX_CT];
	unsigned char ct[crypto_secretbox_ZEROBYTES + MAX_CT];
	pic_u64 box_len = crypto_secretbox_ZEROBYTES + msg_len;
	pic_u32 ct_len;
	pic_u8 len_buf[4];

	if (msg_len > MAX_CT)
		return -1;

	randombytes(nonce, sizeof(nonce));
	pic_memset(pt, 0, crypto_secretbox_ZEROBYTES);
	pic_memcpy(pt + crypto_secretbox_ZEROBYTES, msg, msg_len);

	crypto_secretbox(ct, pt, box_len, nonce, key);

	ct_len = (pic_u32)(box_len - crypto_secretbox_BOXZEROBYTES);
	len_buf[0] = (pic_u8)(ct_len);
	len_buf[1] = (pic_u8)(ct_len >> 8);
	len_buf[2] = (pic_u8)(ct_len >> 16);
	len_buf[3] = (pic_u8)(ct_len >> 24);

	if (write_all(fd, nonce, sizeof(nonce)) < 0)
		return -1;
	if (write_all(fd, len_buf, 4) < 0)
		return -1;
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
	int sock, conn;
	long pt_len;

	/* Create listening socket. */
	sock = (int)pic_socket(PIC_AF_INET, PIC_SOCK_STREAM, 0);
	if (sock < 0)
		pic_exit_group(1);

	int one = 1;
	pic_setsockopt(
		sock, PIC_SOL_SOCKET, PIC_SO_REUSEADDR, &one, sizeof(one));

	struct pic_sockaddr_in addr;
	pic_memset(&addr, 0, sizeof(addr));
	addr.sin_family = PIC_AF_INET;
	addr.sin_port = pic_htons(LISTEN_PORT);
	addr.sin_addr = PIC_INADDR_ANY;

	if (pic_bind(sock, &addr, sizeof(addr)) < 0)
		goto fail_sock;
	if (pic_listen(sock, 1) < 0)
		goto fail_sock;

	pic_write(1, tag_listen, sizeof(tag_listen) - 1);

	conn = (int)pic_accept(sock, PIC_NULL, PIC_NULL);
	if (conn < 0)
		goto fail_sock;

	pic_write(1, tag_conn, sizeof(tag_conn) - 1);

	/* Receive and decrypt message. */
	pt_len = recv_decrypt(conn, PSK, pt, sizeof(pt));
	if (pt_len < 0)
		goto fail_conn;

	pic_write(1, tag_recv, sizeof(tag_recv) - 1);
	pic_write(1, pt + crypto_secretbox_ZEROBYTES, (pic_size_t)pt_len);
	pic_write(1, newline, 1);

	/* Send encrypted ACK. */
	if (encrypt_send(conn, PSK, ack_msg, sizeof(ack_msg) - 1) < 0)
		goto fail_conn;

	pic_write(1, tag_ok, sizeof(tag_ok) - 1);
	pic_close(conn);
	pic_close(sock);
	pic_exit_group(0);

fail_conn:
	pic_close(conn);
fail_sock:
	pic_write(2, tag_fail, sizeof(tag_fail) - 1);
	pic_close(sock);
	pic_exit_group(1);
}
