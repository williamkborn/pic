# MOD-005: Windows API Resolution Architecture

## Status
Accepted

## Description

This model describes the architecture of the Windows PEB/TEB walk and DJB2 hash-based function resolution system used by all Windows-targeting blobs.

## Resolution Flow

```
+===========================================================+
| Blob Entry Point                                          |
|                                                           |
|   1. Needs to call VirtualAlloc, WSASocketA, etc.         |
|   2. Calls resolve_function(dll_hash, func_hash)          |
+===========================================================+
                          |
                          v
+===========================================================+
| resolve_function(dll_hash, func_hash)                     |
|                                                           |
|   1. Check cache: if func pointer already resolved,       |
|      return it immediately.                               |
|   2. Otherwise, call find_module(dll_hash) to get         |
|      the DLL base address.                                |
|   3. Call find_export(dll_base, func_hash) to resolve     |
|      the function within the DLL's export table.          |
|   4. Cache the result.                                    |
|   5. Return the function pointer.                         |
+===========================================================+
              |                           |
              v                           v
+===========================+  +============================+
| find_module(dll_hash)     |  | find_export(base, hash)    |
|                           |  |                            |
| 1. Access TEB:            |  | 1. Parse DOS header at     |
|    x86_64: gs:[0x30]      |  |    base address.           |
|    aarch64: arch-specific  |  | 2. Follow e_lfanew to PE   |
| 2. Read PEB pointer from  |  |    signature.              |
|    TEB (offset 0x60 on    |  | 3. Locate export directory |
|    x86_64).               |  |    from data directories.  |
| 3. Read Ldr pointer from  |  | 4. Walk export name table: |
|    PEB.                   |  |    - Read each name string |
| 4. Get InMemoryOrder-     |  |    - Compute DJB2 hash     |
|    ModuleList head.       |  |    - Compare with target   |
| 5. For each entry:        |  |      func_hash             |
|    - Read BaseDllName     |  | 5. On match: look up       |
|      (Unicode)            |  |    ordinal from ordinal    |
|    - Convert to lowercase |  |    table, then address     |
|    - Compute DJB2 hash    |  |    from address table.     |
|    - Compare with target  |  | 6. Check for forwarded     |
|      dll_hash             |  |    export (address within  |
| 6. On match: return       |  |    export dir range):      |
|    DllBase.               |  |    - Parse "DLL.Function"  |
| 7. If not found: return   |  |    - Recursively resolve   |
|    NULL.                  |  | 7. Return function addr.   |
+===========================+  +============================+
```

## TEB Access Detail

### x86_64

```
(conceptual)
TEB is at gs:[0x30]  (self-pointer in TEB)
PEB is at TEB + 0x60

Accessing TEB requires reading from the gs segment register.
This is a single instruction (mov rax, gs:[0x30]) but cannot
be expressed in portable C. This is the one piece of
architecture-specific inline assembly or accessor function
required for Windows targets, beyond the TEB/PEB offsets
which are C-level struct field accesses.
```

### aarch64

```
(conceptual)
On Windows ARM64, the TEB is accessed via a dedicated register
or memory-mapped location per the Windows ARM64 ABI.
The exact mechanism will be documented during implementation
based on the Windows ARM64 ABI specification.
```

## DJB2 Hash Computation

```
(conceptual algorithm)
hash = 5381
for each byte in input:
    hash = hash * 33 + byte
return hash as uint32

For DLL names: input = lowercase(ascii(BaseDllName))
For function names: input = ascii(export_name) (case-sensitive)
```

## PEB Structure Offsets (x86_64)

```
TEB (Thread Environment Block):
  +0x30: Self pointer (TEB address)
  +0x60: PEB pointer

PEB (Process Environment Block):
  +0x18: Ldr (PEB_LDR_DATA pointer)

PEB_LDR_DATA:
  +0x20: InMemoryOrderModuleList (LIST_ENTRY)

LDR_DATA_TABLE_ENTRY (InMemoryOrder):
  +0x00: InMemoryOrderLinks (LIST_ENTRY)
  +0x20: DllBase (module base address)
  +0x28: EntryPoint
  +0x30: SizeOfImage
  +0x38: FullDllName (UNICODE_STRING)
  +0x48: BaseDllName (UNICODE_STRING)

Note: These offsets are for x86_64 (64-bit pointers).
32-bit offsets would differ but are not needed (Windows
targets are x86_64 and aarch64 only, both 64-bit).
```

## Export Directory Parsing

```
PE at DllBase:
  +0x00: DOS Header
    +0x3C: e_lfanew (offset to PE signature)

  PE Signature + COFF Header + Optional Header:
    Optional Header Data Directories[0] = Export Directory RVA + Size

Export Directory:
  +0x18: NumberOfNames
  +0x1C: AddressOfFunctions (RVA to address table)
  +0x20: AddressOfNames (RVA to name pointer table)
  +0x24: AddressOfNameOrdinals (RVA to ordinal table)

Resolution:
  For i in 0..NumberOfNames:
    name_rva = AddressOfNames[i]
    name_str = DllBase + name_rva
    if djb2(name_str) == target_hash:
      ordinal = AddressOfNameOrdinals[i]
      func_rva = AddressOfFunctions[ordinal]
      func_addr = DllBase + func_rva
      if func_addr is within export directory range:
        -> forwarded export, parse and recurse
      else:
        return func_addr
```

## Resolved Function Cache

```
(conceptual)
struct win_api_cache {
    void* VirtualAlloc;
    void* VirtualProtect;
    void* VirtualFree;
    void* LoadLibraryA;
    void* GetProcAddress;
    void* ExitProcess;
    // ... per blob type
};

The cache struct is part of the blob's .bss or stack frame.
On first use, each slot is NULL. The resolve_function wrapper
checks the slot before doing a full PEB walk. After resolution,
the pointer is stored in the slot for reuse.
```

## Derives From
- REQ-005
- REQ-006
