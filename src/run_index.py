"""Durable run index for reproducibility.

Writes JSONL entries to results/run_index.jsonl.
Each line is a single run summary that can be aggregated later.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional


def _sha256_dir(dir_path: Path) -> str:
    """Hash a directory contents deterministically (names + bytes).

    This is intentionally simple and potentially slow for huge corpora.
    For thesis reproducibility (small demo runs), it's acceptable.
    """

    h = hashlib.sha256()
    if not dir_path.exists():
        return h.hexdigest()

    for p in sorted([x for x in dir_path.rglob("*") if x.is_file()]):
        rel = p.relative_to(dir_path).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        try:
            h.update(p.read_bytes())
        except Exception:
            continue
        h.update(b"\0")
    return h.hexdigest()


def _git_commit_hash(repo_root: Path) -> Optional[str]:
    # avoid shelling out if not a git repo
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return None

    head = (git_dir / "HEAD")
    if not head.exists():
        return None

    try:
        head_txt = head.read_text().strip()
    except Exception:
        return None

    if head_txt.startswith("ref:"):
        ref = head_txt.split(" ", 1)[1].strip()
        ref_path = git_dir / ref
        if ref_path.exists():
            try:
                return ref_path.read_text().strip()
            except Exception:
                return None
        return None

    # detached head
    return head_txt if head_txt else None


@dataclass
class RunIndexEntry:
    schemaVersion: str
    runId: str
    createdAt: str
    workDir: str
    target: str
    protocol: str
    harnessPath: str
    harnessSha256: str
    corpusDir: str
    corpusSha256: str
    afl: Dict[str, Any]
    coverage: Dict[str, Any]
    scenario: Dict[str, Any]
    crashes: Dict[str, Any]
    gitCommit: Optional[str]


_SCHEMA_VERSION = "1.0"


def append_run_index(
    *,
    repo_root: Path,
    run_id: str,
    work_dir: Path,
    target: str,
    protocol: str,
    harness_path: str,
    corpus_dir: str,
    afl: Dict[str, Any],
    coverage: Dict[str, Any],
    scenario: Dict[str, Any],
    crashes: Dict[str, Any],
    index_path: Optional[Path] = None,
) -> Path:
    repo_root = Path(repo_root)
    work_dir = Path(work_dir)

    hp = Path(harness_path)
    harness_sha = ""
    if hp.exists() and hp.is_file():
        harness_sha = hashlib.sha256(hp.read_bytes()).hexdigest()

    corpus_sha = _sha256_dir(Path(corpus_dir))

    entry = RunIndexEntry(
        schemaVersion=_SCHEMA_VERSION,
        runId=run_id,
        createdAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        workDir=str(work_dir),
        target=str(target),
        protocol=str(protocol),
        harnessPath=str(harness_path),
        harnessSha256=harness_sha,
        corpusDir=str(corpus_dir),
        corpusSha256=corpus_sha,
        afl=afl,
        coverage=coverage,
        scenario=scenario,
        crashes=crashes,
        gitCommit=_git_commit_hash(repo_root),
    )

    out = index_path or (Path("results") / "run_index.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), sort_keys=True) + "\n")

    return out
