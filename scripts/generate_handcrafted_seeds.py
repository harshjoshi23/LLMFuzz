#!/usr/bin/env python3
"""Generate handcrafted seeds for DB and TB harnesses.

Each seed is a binary file containing a sequence of 5-byte commands: [op:u8][arg:u32le].

DB harness (fuzz_shm_db.c):
  Opcodes: INIT=0x01, WRITE=0x02, READ=0x03, RESET=0x04, CORRUPT_FLAG=0x05, MULTI_INIT=0x06
  Block index: bi = (arg >> 29) & 0x3
  Size (INIT): arg & 0x3FF, aligned to 4 unless bit31 set
  Zero-size: if sz==0 && !(arg & 0x10000) → stays 0

TB harness (fuzz_shm_tb.c):
  Opcodes: INIT=0x01, WRITE=0x02, UPDATE=0x03, READ=0x04, RESET=0x05
  Block index: idx = (arg >> 24) & 0x3
  Size (INIT): arg & 0x7FF, aligned to 4 unless bit31 set
"""

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cmd(op: int, arg: int) -> bytes:
    """Encode one 5-byte command."""
    return struct.pack("<BI", op, arg & 0xFFFFFFFF)


def write_seed(directory: Path, name: str, data: bytes, description: str):
    """Write a seed file and print info."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    print(f"  {name:40s} ({len(data):3d}B) → {description}")


# =============================================================================
# DB seeds — target: block 0 (bi=0 → arg bits 29-30 = 0b00)
# =============================================================================
DB_DIR = ROOT / "seeds" / "svc_handcrafted_db"

print("=== DB handcrafted seeds ===")

# Helper: arg for block 0 with size s: top bits 00 → arg = s
def db_arg_b0(size: int, extra_bits: int = 0) -> int:
    """Arg targeting block 0 with given size. bi=(arg>>29)&3 must be 0."""
    return (size & 0x3FF) | extra_bits  # bits 29-30 are 0 → block 0


# --- db_write_size0: INIT block0 with size=0, then WRITE block0 ---
# For size=0 to stick: sz = arg & 0x3FF = 0, and (arg & 0x10000) must be 0
# Then INIT sets cur_size[0]=0, initialized[0]=1
# Then WRITE on block0: initialized → yes, sz=0 → "db_write_size0"
data = cmd(0x01, db_arg_b0(0))  # INIT block0, size=0 (no bit16 → stays 0)
data += cmd(0x02, db_arg_b0(0))  # WRITE block0 → size0 path
write_seed(DB_DIR, "db_write_size0.bin", data,
           "INIT(blk0,sz=0) + WRITE(blk0) → db_write_size0")

# --- db_read_before_init: READ on uninitialized block ---
# Block 0 starts uninitialized. Just send READ with arg targeting block 0.
data = cmd(0x03, db_arg_b0(0))  # READ block0 (not initialized)
write_seed(DB_DIR, "db_read_before_init.bin", data,
           "READ(blk0,uninit) → db_read_before_init")

# --- db_read_size0: INIT block0 with size=0, then READ ---
data = cmd(0x01, db_arg_b0(0))  # INIT block0, size=0
data += cmd(0x03, db_arg_b0(0))  # READ block0 → size0 path
write_seed(DB_DIR, "db_read_size0.bin", data,
           "INIT(blk0,sz=0) + READ(blk0) → db_read_size0")

# --- db_corrupt_before_init: CORRUPT_FLAG on uninitialized block ---
data = cmd(0x05, db_arg_b0(0))  # CORRUPT_FLAG block0 (not initialized)
write_seed(DB_DIR, "db_corrupt_before_init.bin", data,
           "CORRUPT_FLAG(blk0,uninit) → db_corrupt_before_init")

# --- db_corrupt_flag: INIT block0, then CORRUPT_FLAG ---
data = cmd(0x01, db_arg_b0(64))  # INIT block0, size=64 (aligned)
data += cmd(0x05, db_arg_b0(0) | 0x01)  # CORRUPT_FLAG block0, arg&1 → flip bit
write_seed(DB_DIR, "db_corrupt_flag.bin", data,
           "INIT(blk0,sz=64) + CORRUPT_FLAG(blk0) → db_corrupt_flag")

# --- Bonus: db_write_ok + db_read_ok (confirm happy path also) ---
data = cmd(0x01, db_arg_b0(64))  # INIT block0, size=64
data += cmd(0x02, db_arg_b0(0))  # WRITE block0 → write_ok
data += cmd(0x03, db_arg_b0(0))  # READ block0 → read_ok
write_seed(DB_DIR, "db_write_read_ok.bin", data,
           "INIT(blk0,sz=64) + WRITE + READ → db_write_ok, db_read_ok")

# --- db_reset ---
data = cmd(0x01, db_arg_b0(64))  # INIT block0
data += cmd(0x04, 0)              # RESET
write_seed(DB_DIR, "db_reset.bin", data,
           "INIT(blk0) + RESET → db_reset")


# =============================================================================
# TB seeds — target: block 0 (idx=0 → arg bits 24-25 = 0b00)
# =============================================================================
TB_DIR = ROOT / "seeds" / "svc_handcrafted_tb"

print("\n=== TB handcrafted seeds ===")


def tb_arg_b0(size: int, extra_bits: int = 0) -> int:
    """Arg targeting block 0 with given size. idx=(arg>>24)&3 must be 0."""
    return (size & 0x7FF) | extra_bits  # bits 24-25 are 0 → block 0


# --- tb_write_buf: INIT + WRITE (GetWriteBuf returns non-null, size > 0) ---
data = cmd(0x01, tb_arg_b0(64))  # INIT block0, size=64
data += cmd(0x02, tb_arg_b0(0))  # WRITE block0 → GetWriteBuf, memcpy → tb_write_buf
write_seed(TB_DIR, "tb_write_buf.bin", data,
           "INIT(blk0,sz=64) + WRITE → tb_write_buf")

# --- tb_update_write: INIT + UPDATE ---
data = cmd(0x01, tb_arg_b0(64))  # INIT block0, size=64
data += cmd(0x03, tb_arg_b0(0))  # UPDATE block0 → tb_update_write
write_seed(TB_DIR, "tb_update_write.bin", data,
           "INIT(blk0,sz=64) + UPDATE → tb_update_write")

# --- tb_read_buf: INIT + UPDATE + READ (GetReadBuf non-null, size > 0) ---
# Need update first so read buffer points to valid data
data = cmd(0x01, tb_arg_b0(64))  # INIT block0, size=64
data += cmd(0x02, tb_arg_b0(0))  # WRITE → fill write buf
data += cmd(0x03, tb_arg_b0(0))  # UPDATE → swap buffers
data += cmd(0x04, tb_arg_b0(0))  # READ block0 → tb_read_buf
write_seed(TB_DIR, "tb_read_buf.bin", data,
           "INIT+WRITE+UPDATE+READ → tb_read_buf")

# --- tb_get_write_null: WRITE on initialized block where GetWriteBuf returns NULL ---
# This happens when the TB block is initialized but buffers not allocated (size=0 init)
# Actually, GetWriteBuf returns NULL when init didn't allocate properly.
# Try: INIT with size=0 → pool may not allocate → GetWriteBuf returns NULL
data = cmd(0x01, tb_arg_b0(0))   # INIT block0, size=0 (stays 0 if no bit16)
data += cmd(0x02, tb_arg_b0(0))  # WRITE → GetWriteBuf likely NULL → tb_get_write_null
write_seed(TB_DIR, "tb_get_write_null.bin", data,
           "INIT(blk0,sz=0) + WRITE → tb_get_write_null")

# --- tb_write_size0: INIT with size=0 where GetWriteBuf succeeds but sz=0 ---
# This might not be reachable if GetWriteBuf returns NULL for size=0 init.
# Provide it anyway; the scenario that fires will be tb_get_write_null or tb_write_size0.
# Try with a very small size that might round to 0 after alignment
data = cmd(0x01, tb_arg_b0(1) | 0x80000000)  # INIT block0, bit31=1 → no alignment, sz=1
data += cmd(0x02, tb_arg_b0(0))               # WRITE → test if sz leads to write_size0
write_seed(TB_DIR, "tb_write_size0_attempt.bin", data,
           "INIT(blk0,sz=1,unaligned) + WRITE → tb_write_size0 or tb_write_buf")

# --- tb_get_read_null: READ on initialized block where GetReadBuf returns NULL ---
# Before any update, the read buffer may be NULL
data = cmd(0x01, tb_arg_b0(64))  # INIT block0, size=64
data += cmd(0x04, tb_arg_b0(0))  # READ (no update done) → GetReadBuf likely NULL
write_seed(TB_DIR, "tb_get_read_null.bin", data,
           "INIT(blk0,sz=64) + READ(no update) → tb_get_read_null")

# --- tb_read_size0: INIT with size=0, update, then READ ---
data = cmd(0x01, tb_arg_b0(0))   # INIT block0, size=0
data += cmd(0x03, tb_arg_b0(0))  # UPDATE
data += cmd(0x04, tb_arg_b0(0))  # READ → size=0 → tb_read_size0
write_seed(TB_DIR, "tb_read_size0.bin", data,
           "INIT(blk0,sz=0) + UPDATE + READ → tb_read_size0 or tb_get_read_null")

# --- tb_update_before_init: UPDATE on uninitialized block ---
data = cmd(0x03, tb_arg_b0(0))  # UPDATE block0 (not initialized)
write_seed(TB_DIR, "tb_update_before_init.bin", data,
           "UPDATE(blk0,uninit) → tb_update_before_init")

# --- tb_reset: INIT + RESET ---
data = cmd(0x01, tb_arg_b0(64))  # INIT block0
data += cmd(0x05, tb_arg_b0(0))  # RESET block0
write_seed(TB_DIR, "tb_reset.bin", data,
           "INIT(blk0,sz=64) + RESET → tb_reset")

# --- tb_read_before_init: READ on uninitialized block ---
data = cmd(0x04, tb_arg_b0(0))  # READ block0 (not initialized)
write_seed(TB_DIR, "tb_read_before_init.bin", data,
           "READ(blk0,uninit) → tb_read_before_init")

# --- Bonus: full lifecycle ---
data = cmd(0x01, tb_arg_b0(128))  # INIT
data += cmd(0x02, tb_arg_b0(0))   # WRITE → tb_write_buf
data += cmd(0x03, tb_arg_b0(0))   # UPDATE → tb_update_write
data += cmd(0x04, tb_arg_b0(0))   # READ → tb_read_buf
data += cmd(0x05, tb_arg_b0(0))   # RESET → tb_reset
write_seed(TB_DIR, "tb_full_lifecycle.bin", data,
           "INIT+WRITE+UPDATE+READ+RESET → full lifecycle")

print(f"\nDone. Seeds at:")
print(f"  DB: {DB_DIR}")
print(f"  TB: {TB_DIR}")
