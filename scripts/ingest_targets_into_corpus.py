#!/usr/bin/env python3
"""
Ingest files from targets/ into the RAG corpus directory so the LLM
has access to protocol definitions, headers, comments, and docs.

This copies .c/.h/.md/.txt/.rst files from targets/ into

    data/vectorstore_projects/<project>/corpus

The RAG pipeline already indexes that folder, so no deeper code
changes are required.
"""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "targets"
CORPUS = ROOT / "data/vectorstore_projects/infineon-dc-optimizer/corpus"

VALID_EXT = {".md", ".txt", ".rst", ".c", ".h"}


def main():
    if not TARGETS.exists():
        raise SystemExit("targets/ directory not found")

    CORPUS.mkdir(parents=True, exist_ok=True)

    copied = 0

    for f in TARGETS.rglob("*"):
        if f.suffix.lower() in VALID_EXT and f.is_file():
            dst = CORPUS / f"{f.parent.name}_{f.name}"
            try:
                shutil.copy(f, dst)
                copied += 1
            except Exception:
                pass

    print(f"[Ingest] copied {copied} files into corpus")


if __name__ == "__main__":
    main()
