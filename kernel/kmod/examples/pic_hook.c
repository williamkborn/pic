/*
 * pic_hook.c — PIC blob that spawns a kthread and returns to the caller.
 *
 * When loaded via !kload, this blob:
 *   1. Resolves printk and kthread_run via kprobes
 *   2. Spawns a new kthread that periodically prints to dmesg
 *   3. Returns immediately — the shell stays alive
 *   4. The spawned kthread runs independently in kernel context
 *
 * This demonstrates the pattern for persistent kernel payloads:
 * the blob is a "dropper" that installs something and returns.
 *
 * Build as a kernel module (for the toolchain), then extract .text:
 *   make -C /lib/modules/$(uname -r)/build M=$(pwd) modules
 *   objcopy -O binary -j .text pic_hook.ko pic_hook.bin
 *
 * Or build directly as a flat binary with the project's PIC toolchain.
 *
 * Load via kshell:
 *   !kload pic_hook.bin
 *
 * Verify in dmesg:
 *   dmesg | grep pic_hook
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/kthread.h>
#include <linux/kprobes.h>
#include <linux/delay.h>

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("PIC blob example — spawn kthread and return");

/*
 * The hook function — runs as an independent kthread after the blob returns.
 * Prints a message every 10 seconds to prove it's alive.
 * In a real scenario, this would install a syscall hook, network filter,
 * keylogger, etc.
 */
static int hook_thread(void *data)
{
    int count = 0;

    printk(KERN_INFO "pic_hook: kthread started (independent of loader)\n");

    while (!kthread_should_stop() && count < 6) {
        printk(KERN_INFO "pic_hook: alive in ring 0 (tick %d)\n", count++);
        ssleep(10);
    }

    printk(KERN_INFO "pic_hook: kthread exiting after %d ticks\n", count);
    return 0;
}

/*
 * _start — Blob entry point.
 *
 * When called via !kload, this function runs in the kshell's kthread
 * context. It must return quickly so the shell stays responsive.
 *
 * We spawn a new kthread (hook_thread) that runs independently.
 * After kthread_run returns, we return to the shell — hook_thread
 * continues running on its own.
 */
static int __init pic_hook_init(void)
{
    struct task_struct *t;

    printk(KERN_INFO "pic_hook: dropper executing in ring 0\n");
    printk(KERN_INFO "pic_hook: spawning independent kthread...\n");

    t = kthread_run(hook_thread, NULL, "pic_hook");
    if (IS_ERR(t)) {
        printk(KERN_INFO "pic_hook: kthread_run failed: %ld\n", PTR_ERR(t));
        return PTR_ERR(t);
    }

    printk(KERN_INFO "pic_hook: kthread spawned (PID %d), returning to shell\n",
           t->pid);

    /* Return 0 — the shell continues, the hook runs independently */
    return 0;
}

static void __exit pic_hook_exit(void)
{
    printk(KERN_INFO "pic_hook: module unloaded\n");
}

module_init(pic_hook_init);
module_exit(pic_hook_exit);
