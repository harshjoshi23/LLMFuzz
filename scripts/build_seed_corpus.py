#!/usr/bin/env python3
"""
Seed Corpus Builder for Thesis Fuzzing Pipeline

This script automatically builds an initial fuzzing corpus by combining:
1. Static extraction from source code (enums / CMD / PMBUS / registers)
2. Unit test input discovery
3. Simple structured seeds for algorithms (MPPT, 3P3Z, PLL)

Output directory:
    data/seeds/<target>/

This corpus is intentionally simple and deterministic so that
AFL++ can mutate and expand it further.
"""

import os
import re
import pathlib
import struct

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS_DIR = ROOT / "targets"
SEED_DIR = ROOT / "data" / "seeds"

KEY_PATTERNS = [
    r"CMD_[A-Z0-9_]+",
    r"PMBUS_[A-Z0-9_]+",
    r"REG_[A-Z0-9_]+",
]


def ensure_dirs():
    (SEED_DIR / "i2c").mkdir(parents=True, exist_ok=True)
    (SEED_DIR / "pmbus").mkdir(parents=True, exist_ok=True)
    (SEED_DIR / "mppt").mkdir(parents=True, exist_ok=True)
    (SEED_DIR / "3p3z").mkdir(parents=True, exist_ok=True)
    (SEED_DIR / "pll").mkdir(parents=True, exist_ok=True)


def extract_constants():
    """Scan target repos for protocol constants."""
    tokens = set()

    for path in TARGETS_DIR.rglob("*.h"):
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue

        for pat in KEY_PATTERNS:
            for m in re.findall(pat, text):
                tokens.add(m)

    return sorted(tokens)


def write_protocol_seeds(tokens):
    """Write simple ASCII seeds for protocol fuzzing."""
    for i, tok in enumerate(tokens[:50]):
        f = SEED_DIR / "i2c" / f"seed_{i:03d}.bin"
        f.write_bytes(tok.encode("ascii"))


def write_mppt_seeds():
    """Generate numeric seeds for MPPT algorithm."""
    samples = [
        (12.0, 1.0),
        (24.0, 2.5),
        (36.0, 4.0),
        (48.0, 5.0),
        (60.0, 6.0),
    ]

    for i, (v, c) in enumerate(samples):
        data = struct.pack("ff", v, c)
        (SEED_DIR / "mppt" / f"seed_{i:03d}.bin").write_bytes(data)


def write_filter_seeds():
    samples = [
        (100, 200),
        (200, 300),
        (-100, 50),
        (0, 0),
        (32767, -32768),
    ]

    for i, (a, b) in enumerate(samples):
        data = struct.pack("hh", a, b)
        (SEED_DIR / "3p3z" / f"seed_{i:03d}.bin").write_bytes(data)


def write_pll_seeds():
    samples = [
        (0.1, 0.1),
        (0.5, 0.5),
        (1.0, 1.0),
        (3.14, 2.0),
        (6.28, 3.0),
    ]

    for i, (a, b) in enumerate(samples):
        data = struct.pack("ff", a, b)
        (SEED_DIR / "pll" / f"seed_{i:03d}.bin").write_bytes(data)


def main():
    ensure_dirs()

    print("[Corpus] extracting protocol constants from source...")
    tokens = extract_constants()

    print(f"[Corpus] found {len(tokens)} tokens")

    write_protocol_seeds(tokens)
    write_mppt_seeds()
    write_filter_seeds()
    write_pll_seeds()

    print("[Corpus] seed corpus generated in data/seeds/")


if __name__ == "__main__":
    main()
