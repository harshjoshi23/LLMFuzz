"""Artifact contract validation for evaluation-grade runs.

This module defines what a "complete" run means.

Design goals:
- Generic: not tied to any specific target repo.
- Deterministic: validates presence of canonical artifacts and key metrics.
- Actionable: returns structured errors suitable for CLI + dashboard.

A run can still be considered valid even if some optional artifacts are missing,
provided the mandatory set is present.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ArtifactError:
    path: str
    message: str


@dataclass
class ArtifactCheckResult:
    ok: bool
    errors: list[ArtifactError]
    warnings: list[ArtifactError]


MANDATORY_RELATIVE_PATHS = [
    "run.json",
    "reports/fuzzing_report.md",
    "reports/fuzzing_report.json",
]

OPTIONAL_RELATIVE_PATHS = [
    "reports/report.html",
    "reports/report.junit.xml",
    "reports/scenario_coverage.json",
    "reports/scenario_summary.md",
    "reports/scenario_summary.csv",
]


def validate_run_artifacts(*, run_dir: Path) -> ArtifactCheckResult:
    errors: list[ArtifactError] = []
    warnings: list[ArtifactError] = []

    if not run_dir.exists():
        return ArtifactCheckResult(
            ok=False,
            errors=[ArtifactError(path=str(run_dir), message="run dir does not exist")],
            warnings=[],
        )

    for rel in MANDATORY_RELATIVE_PATHS:
        p = run_dir / rel
        if not p.exists():
            errors.append(ArtifactError(path=str(p), message="missing mandatory artifact"))

    for rel in OPTIONAL_RELATIVE_PATHS:
        p = run_dir / rel
        if not p.exists():
            warnings.append(ArtifactError(path=str(p), message="missing optional artifact"))

    # Light sanity check: ensure run.json is non-empty
    rj = run_dir / "run.json"
    if rj.exists() and rj.stat().st_size < 10:
        errors.append(ArtifactError(path=str(rj), message="run.json appears empty/truncated"))

    return ArtifactCheckResult(ok=(len(errors) == 0), errors=errors, warnings=warnings)


def enrich_run_metadata(*, run_obj: dict[str, Any], repo_root: Path) -> None:
    """Attach reproducibility metadata into run.json structure.

    This should NOT include secrets.
    """

    # Git metadata best-effort; do not fail pipeline if unavailable.
    try:
        import subprocess

        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_root)).decode().strip()
        dirty = subprocess.call(["git", "diff", "--quiet"], cwd=str(repo_root)) != 0
        run_obj.setdefault("environment", {})
        run_obj["environment"].update({"gitCommit": commit, "gitDirty": bool(dirty)})
    except Exception:
        pass

    # Tool versions best-effort
    try:
        import sys

        run_obj.setdefault("environment", {})
        run_obj["environment"].update({"python": sys.version.split()[0]})
    except Exception:
        pass
