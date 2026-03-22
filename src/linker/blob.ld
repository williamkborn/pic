/*
 * picblobs linker script — controls blob binary layout (ADR-003).
 *
 * Layout (all 16-byte aligned, base 0):
 *
 *   .text.pic_entry  — blob entry point (PIC_ENTRY)
 *   .text.pic_code   — blob code (PIC_TEXT)
 *   .text            — any remaining text
 *   .rodata          — read-only data (PIC_RODATA)
 *   .got / .got.plt  — GOT (needed by 32-bit arches for PIC)
 *   .data            — writable data (PIC_DATA)
 *   .bss             — zero-initialized data (PIC_BSS)
 *   .config          — config struct (PIC_CONFIG, appended at runtime)
 *
 * Symbols:
 *   __blob_start   — first byte of blob (== entry point)
 *   __blob_end     — end of blob data (before .config)
 *   __config_start — start of config section
 */

ENTRY(_start)

SECTIONS
{
    . = 0;

    __blob_start = .;

    .text.pic_trampoline : ALIGN(16) {
        KEEP(*(.text.pic_trampoline))
    }

    .text.pic_entry : ALIGN(16) {
        KEEP(*(.text.pic_entry))
    }

    .text.pic_code : ALIGN(16) {
        KEEP(*(.text.pic_code))
    }

    .text : ALIGN(16) {
        KEEP(*(.text .text.*))
    }

    .plt : ALIGN(16) {
        KEEP(*(.plt .plt.*))
    }

    .rodata : ALIGN(16) {
        KEEP(*(.rodata .rodata.* .rodata.pic))
    }

    .got : ALIGN(16) {
        __got_start = .;
        KEEP(*(.got))
        KEEP(*(.got.plt))
        __got_end = .;
    }

    .data : ALIGN(16) {
        KEEP(*(.data .data.* .data.pic))
    }

    .data.rel.ro : ALIGN(16) {
        KEEP(*(.data.rel.ro .data.rel.ro.*))
    }

    .bss : ALIGN(16) {
        KEEP(*(.bss .bss.* .bss.pic))
        KEEP(*(COMMON))
    }

    __blob_end = .;

    .config : ALIGN(16) {
        __config_start = .;
        KEEP(*(.config .config.*))
    }

    /*
     * Discarded sections — including all relocations (.rela.*, .rel.*).
     *
     * Relocations are discarded because blobs must be fully position-
     * independent with no absolute references. If a blob ever contains
     * a global pointer init or constructor pattern that emits relocations,
     * the linker will silently produce wrong addresses at runtime.
     * The QEMU test runner validates correct execution; add an explicit
     * relocation-table-empty check if this becomes a concern.
     */
    /DISCARD/ : {
        *(.comment)
        *(.note.*)
        *(.eh_frame)
        *(.eh_frame_hdr)
        *(.hash)
        *(.gnu.hash)
        *(.dynsym)
        *(.dynstr)
        *(.dynamic)
        *(.rela.*)
        *(.rel.*)
        *(.interp)
    }
}
