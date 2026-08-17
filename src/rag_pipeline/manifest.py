"""RAG index manifest for incremental rebuild decisions.

Goal (thesis/generic framework):
- Keep a per-project knowledge base (corpus + vector index).
- Automatically rebuild the index when docs change.

We implement a simple offline-first approach:
- After ingesting docs into <index_dir>/corpus, compute a manifest:
  - file list + size + mtime
- On next run, compare current corpus snapshot to stored manifest.

This avoids unnecessary embedding calls and keeps runs reproducible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


MANIFEST_FILENAME = "rag_manifest.json"


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    # size + mtime are often enough, but content-hash is safer for correctness.
    # keep it simple and deterministic.
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RagManifest:
    # Relative paths under corpus_dir
    files: dict[str, dict]

    @staticmethod
    def _manifest_path(index_dir: Path) -> Path:
        return index_dir / MANIFEST_FILENAME

    @classmethod
    def load(cls, index_dir: Path) -> "RagManifest":
        p = cls._manifest_path(index_dir)
        data = json.loads(p.read_text(encoding="utf-8"))
        files = data.get("files", {}) or {}
        if not isinstance(files, dict):
            raise ValueError("invalid manifest: files must be object")
        return cls(files=files)

    @classmethod
    def write(cls, index_dir: Path, corpus_dir: Path) -> None:
        index_dir = Path(index_dir)
        corpus_dir = Path(corpus_dir)
        index_dir.mkdir(parents=True, exist_ok=True)

        files = {}
        for f in sorted(corpus_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(corpus_dir))
            st = f.stat()
            files[rel] = {
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "sha256": _hash_file(f),
            }

        out = {"files": files}
        cls._manifest_path(index_dir).write_text(json.dumps(out, indent=2), encoding="utf-8")

    def is_up_to_date(self, corpus_dir: Path) -> bool:
        corpus_dir = Path(corpus_dir)
        if not corpus_dir.exists():
            return False

        current = {}
        for f in sorted(corpus_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(corpus_dir))
            st = f.stat()
            current[rel] = {
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "sha256": _hash_file(f),
            }

        # Compare only content-identity fields (size + sha256).
        # mtime is intentionally ignored: `git pull` / `git clone` rewrites file
        # timestamps to "now", which would otherwise force an unnecessary rebuild
        # (and an LLM/auth call) on every fresh checkout even when the bytes are
        # identical. Content hash is canonical.
        def _identity(d: dict) -> dict:
            return {
                rel: {"size": meta.get("size"), "sha256": meta.get("sha256")}
                for rel, meta in (d or {}).items()
            }

        return _identity(current) == _identity(self.files)
