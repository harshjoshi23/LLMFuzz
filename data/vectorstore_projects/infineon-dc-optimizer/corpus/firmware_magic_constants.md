# Infineon DC Optimizer — Vendor Diagnostic Constants

This document lists the magic byte sequences that gate the vendor diagnostic
and unlock command surface of the DC optimizer firmware. The values are taken
from the firmware build artifacts and the vendor command reference.

## Diagnostic unlock commands (case 0xE0..0xE5)

### VENDOR_DIAG_UNLOCK_KEY
Required leading magic to access diagnostic mode (command 0xE0).
- Value: `0xCAFEBABE`
- Byte sequence (big-endian as transmitted): `0xCA 0xFE 0xBA 0xBE`
- Width: 4 bytes
- After unlock, byte 5 selects diagnostic op 0..5.

### VENDOR_SIGNATURE_KEY
Vendor identification string for command 0xE1. Required to enter
calibration sub-command space.
- Value: ASCII `"IFXD"` = `0x49464858 0x44`
- Byte sequence: `0x49 0x46 0x58 0x44`
- Width: 4 bytes
- Subcommands 0x10..0x13 follow, with calibration value in bytes 6..7.

### VENDOR_CAL_TAG_TOKEN
Two-stage calibration token for command 0xE2.
- Tag value (little-endian on wire): `0xC0DE` → `0xDE 0xC0`
- Byte 3: calibration ID (0..0xFF)
- Byte 4: checksum = `ID XOR 0x5A`
- Width: 4 bytes total payload after command byte

### VENDOR_FIRMWARE_TOKEN
8-byte firmware identification token for command 0xE3.
Required to invoke the protected firmware-introspection branch.
- Value: `0x49 0x46 0x58 0xD0 0xC0 0x07 0x10 0x01`
- ASCII prefix: `"IFX"`, vendor marker `0xD0`, build code `0xC0071001`
- Width: 8 bytes

### VENDOR_XOR_CHALLENGE_KEY
XOR-based challenge for command 0xE4. The 4-byte payload must satisfy:
`payload XOR 0xDEADBEEF == 0xCAFEBABE`. Solving by inspection:
`payload = 0xDEADBEEF XOR 0xCAFEBABE = 0x14470455`.
- XOR mask: `0xDEADBEEF`
- Expected result: `0xCAFEBABE`
- Solved payload (little-endian on wire): `0x55 0x04 0x47 0x14`
- Width: 4 bytes; byte 5 selects mode 0..5.

### VENDOR_CHAINED_SEQUENCE_KEY
Three-byte magic prefix for command 0xE5 that gates a four-way action switch.
- Value: `0xACCE55` ("ACCESS" written in hex)
- Byte sequence (big-endian on wire): `0xAC 0xCE 0x55`
- Width: 3 bytes + 1-byte action selector
- Action field is `data[4] & 0x03`, exposing four sub-branches.

## Extended PMBus command surface (PMBus 1.3 §11)

The firmware accepts the following standard PMBus paging and NVM commands
in addition to the vendor-specific surface above. They are not magic-gated
and any conformant PMBus master can issue them.

- `0x00 PAGE` (rail select, valid pages 0..3 plus 0xFF broadcast)
- `0x15 STORE_USER_ALL`
- `0x16 RESTORE_USER_ALL`
- `0x17 STORE_DEFAULT_ALL`
- `0x18 RESTORE_DEFAULT_ALL`

## EEPROM access (DC Optimizer v5 §6.3)

- `0xC0 EEPROM_READ`  : `[0xC0, addr_lo, addr_hi]`
- `0xC1 EEPROM_WRITE` : `[0xC1, addr_lo, addr_hi, value]`
- Address space: 2 KiB, word-aligned (LSB of `addr` must be 0).
- Boot block at `[0x0000, 0x000F]` is locked: writes only succeed with
  `value == 0xFF`.

## Encoding notes

All diagnostic commands (0xE0..0xE5) are I2C/PMBus single frames of the
form `[cmd_byte][magic_bytes][optional_payload]`. Random fuzzing cannot
discover these gates within practical time budgets; the seed generator
must inject them based on this constant table.
