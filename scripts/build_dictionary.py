#!/usr/bin/env python3
"""
Protocol Dictionary Generator

Creates AFL dictionaries from extracted tokens in the target repositories.
These help AFL discover valid protocol states faster.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = ROOT / "targets"
DICT_DIR = ROOT / "data" / "dictionaries"

PATTERNS = [
    r"CMD_[A-Z0-9_]+",
    r"PMBUS_[A-Z0-9_]+",
    r"REG_[A-Z0-9_]+",
]


def extract_tokens():
    tokens = set()

    for path in TARGETS.rglob("*.h"):
        try:
            txt = path.read_text(errors="ignore")
        except Exception:
            continue

        for pat in PATTERNS:
            for m in re.findall(pat, txt):
                tokens.add(m)

    return sorted(tokens)


def write_dict(tokens):
    DICT_DIR.mkdir(parents=True, exist_ok=True)

    dict_file = DICT_DIR / "protocol.dict"

    with open(dict_file, "w") as f:
        for t in tokens:
            f.write(f'"{t}"\n')

    print(f"[Dictionary] wrote {len(tokens)} tokens -> {dict_file}")


if __name__ == "__main__":
    tokens = extract_tokens()
    write_dict(tokens)
