from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.blackboard import bb_event


@dataclass
class EntrypointCandidate:
    function: str
    score: float
    evidence: Dict[str, Any]


def _scan_headers_for_candidates(repo: Path, max_candidates: int = 3) -> List[EntrypointCandidate]:
    """Very lightweight heuristic candidate finder.

    This is intentionally conservative:
    - look for header prototypes that look like public APIs
    - prefer functions with names like init/run/process/step/update/execute

    This is NOT a full parser. The goal is to propose candidates so the user can
    commit the choice into the manifest (Option A).
    """

    import re

    patterns = [
        re.compile(r"\b(init|initialize|run|process|step|update|execute)\w*\s*\(", re.IGNORECASE),
    ]

    candidates: Dict[str, EntrypointCandidate] = {}

    hdrs = list(repo.rglob("*.h")) + list(repo.rglob("*.hpp"))
    for hp in hdrs[:200]:  # cap for speed
        try:
            txt = hp.read_text(errors="replace")
        except Exception:
            continue

        for pat in patterns:
            for m in pat.finditer(txt):
                fn = m.group(0).split("(")[0].strip()
                # Strip return type fragments if accidentally captured
                fn = fn.split()[-1]
                if len(fn) < 3:
                    continue
                if fn not in candidates:
                    candidates[fn] = EntrypointCandidate(
                        function=fn,
                        score=1.0,
                        evidence={"file": str(hp), "pattern": pat.pattern},
                    )
                else:
                    candidates[fn].score += 0.2

    out = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
    return out[:max_candidates]


def propose_entrypoints(target_repo: Path, max_candidates: int = 3) -> List[EntrypointCandidate]:
    target_repo = Path(target_repo)
    bb_event(
        "HarnessAgent",
        "entrypoint_scan_started",
        target_repo=str(target_repo),
        max_candidates=max_candidates,
    )

    cands = _scan_headers_for_candidates(target_repo, max_candidates=max_candidates)

    bb_event(
        "HarnessAgent",
        "entrypoint_scan_finished",
        target_repo=str(target_repo),
        candidates=[{"function": c.function, "score": c.score, "evidence": c.evidence} for c in cands],
    )

    return cands


def write_entrypoint_candidates_to_manifest(*, manifest_path: Path, candidates: List[EntrypointCandidate]) -> None:
    """Write candidates under fuzz.harness.entrypoint_candidates (non-destructive)."""

    import yaml

    mp = Path(manifest_path)
    doc = yaml.safe_load(mp.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"Manifest must be mapping: {mp}")

    fuzz = doc.setdefault("fuzz", {})
    harness = fuzz.setdefault("harness", {})

    harness["entrypoint_candidates"] = [
        {"function": c.function, "score": float(c.score), "evidence": c.evidence} for c in candidates
    ]

    mp.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    bb_event(
        "HarnessAgent",
        "manifest_candidates_written",
        manifest=str(mp),
        count=len(candidates),
    )


def read_selected_entrypoint_from_manifest(manifest_path: Path) -> Optional[str]:
    import yaml

    mp = Path(manifest_path)
    doc = yaml.safe_load(mp.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return None

    try:
        return str(doc["fuzz"]["harness"].get("entrypoint") or "").strip() or None
    except Exception:
        return None
