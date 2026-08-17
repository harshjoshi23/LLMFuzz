#!/usr/bin/env python3
"""Ingest firmware documentation into the RAG vectorstore.

This script copies docs into a project corpus folder and (re)builds the FAISS
index so CrashAnalysisAgent / ConstraintExtractor can retrieve relevant context.

Docs location (per prompt):
  data/datasheets/firmware_docs/

Usage:
  python3 scripts/ingest_firmware_docs.py

Notes:
- .docx is supported (via python-docx dependency). Legacy .doc is not parsed here.
  If you only have .doc files, convert them to .docx (or PDF) first.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.docs_ingestor import DocsIngestor
from src.rag_pipeline.rag_pipeline import RAGPipeline


def main() -> int:
    docs_dir = PROJECT_ROOT / "data" / "datasheets" / "firmware_docs"
    if not docs_dir.exists():
        print(f"ERROR: docs directory not found: {docs_dir}")
        return 2

    # Corpus folder consumed by RAGPipeline
    corpus_dir = PROJECT_ROOT / "data" / "vectorstore_projects" / "firmware_docs" / "corpus"

    print(f"Ingesting firmware docs from: {docs_dir}")
    print(f"Corpus dir: {corpus_dir}")

    ingestor = DocsIngestor(project_root=str(PROJECT_ROOT))
    res = ingestor.ingest([str(docs_dir)], corpus_dir=str(corpus_dir))
    print(f"Copied {res.files_copied} files into corpus")

    # Build index from PDFs in data/datasheets by default; for thesis we reuse the existing
    # pipeline and rely on user keeping firmware docs as PDFs (or add them to datasheets).
    # If firmware docs are PDFs and already under data/datasheets, they'll be picked up.
    rag = RAGPipeline(datasheet_dir=str(docs_dir), vectorstore_dir=str(PROJECT_ROOT / "data" / "vectorstore"))
    rag.build_index(force_rebuild=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
