/* _start — ARM: extract argc/argv from kernel stack, call runner_main. */
__asm__(".section .text._start,\"ax\"\n"
	".globl _start\n"
	"_start:\n"
	"  ldr r0, [sp]\n"
	"  add r1, sp, #4\n"
	"  bl runner_main\n"
	"  mov r7, #248\n"
	"  svc #0\n");
