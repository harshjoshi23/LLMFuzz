"""Dashboard models: read run index and run artifacts.

This is intentionally dependency-free.

Data sources:
- results/run_index.jsonl (append-only)
- results/<run_id>/run.json
- results/<run_id>/reports/*

We keep this separate so that:
- static dashboard generation and Flask serving reuse the same model
- the rest of the fuzzing pipeline remains untouched
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class RunRow:
    run_id: str
    work_dir: str
    harness: str
    target: str
    started_at: str
    status: str
    bitmap_coverage_percent: float
    queue_size: int
    total_crashes: int

    scenario_coverage: float
    scenarios_observed: int
    scenarios_expected: int

    report_html: str
    report_json: str
    scenario_json: str
    scenario_md: str
    scenario_html: str


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def iter_run_index(index_path: Path) -> Iterable[Dict[str, Any]]:
    if not index_path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def load_hidden_run_ids(repo_root: Path) -> set[str]:
    p = repo_root / "results" / ".dashboard_hidden_runs.txt"
    if not p.exists():
        return set()
    out: set[str] = set()
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.add(s)
    return out


def load_runs(repo_root: Path) -> List[RunRow]:
    hidden = load_hidden_run_ids(repo_root)

    index_path = repo_root / "results" / "run_index.jsonl"
    rows: List[RunRow] = []

    for rec in iter_run_index(index_path):
        # Support both the canonical run index schema (RunIndexEntry)
        # and older ad-hoc variants.
        run_id = str(rec.get("run_id") or rec.get("runId") or "")
        if run_id and run_id in hidden:
            continue
        work_dir = rec.get("work_dir") or rec.get("workDir")
        if isinstance(work_dir, str) and work_dir:
            wd = Path(work_dir)
        else:
            wd = repo_root / "results" / run_id

        run_json = _safe_load_json(wd / "run.json")

        # Prefer canonical (schema-valid) run.json fields.
        # Backward-compat: fall back to legacy `summary` if present.
        summary = run_json.get("summary", {}) if isinstance(run_json.get("summary"), dict) else {}
        extras = run_json.get("extras", {}) if isinstance(run_json.get("extras"), dict) else {}
        afl = extras.get("afl", {}) if isinstance(extras.get("afl"), dict) else {}

        # AFL: different parts of the code have used different key names over time.
        # Prefer current keys first, then fall back to older ones.
        # Also: some pipelines write AFL metrics to results/<run_id>/afl/<protocol>/run.json
        # and only keep paths in results/<run_id>/run.json.
        bitmap_cov = afl.get("bitmap_coverage_percent")
        if bitmap_cov is None:
            bitmap_cov = afl.get("coverage_percent")
        if bitmap_cov is None and isinstance(afl.get("coverage"), dict):
            bitmap_cov = afl.get("coverage", {}).get("bitmap_coverage_percent")

        queue_sz = afl.get("queue_size")
        crashes = afl.get("crashes_found")

        # Fall back to AFL sub-run run.json if needed
        afl_out_dir = afl.get("output_dir")
        if afl_out_dir and (bitmap_cov is None or queue_sz is None or crashes is None):
            afl_run_json = Path(str(afl_out_dir)) / "run.json"
            afl_run = _safe_load_json(afl_run_json)
            if bitmap_cov is None:
                bitmap_cov = afl_run.get("bitmap_coverage_percent")
            if queue_sz is None:
                queue_sz = afl_run.get("queue_size")
            if crashes is None:
                crashes = afl_run.get("crashes_found")

        if bitmap_cov is None:
            bitmap_cov = summary.get("bitmap_coverage_percent")
        if bitmap_cov is None:
            bitmap_cov = rec.get("afl", {}).get("bitmap_coverage_percent") if isinstance(rec.get("afl"), dict) else None

        if queue_sz is None:
            queue_sz = summary.get("queue_size")
        if queue_sz is None:
            queue_sz = rec.get("afl", {}).get("queue_size") if isinstance(rec.get("afl"), dict) else None

        if crashes is None:
            crashes = summary.get("total_crashes")
        if crashes is None:
            crashes = rec.get("afl", {}).get("crashes_found") if isinstance(rec.get("afl"), dict) else None

        harness = str(
            rec.get("harness")
            or rec.get("protocol")
            or run_json.get("harness")
            or run_json.get("protocol")
            or ""
        )
        target = str(
            rec.get("target")
            or run_json.get("target")
            or ""
        )

        reports_dir = wd / "reports"
        report_html = reports_dir / "report.html"
        report_json = reports_dir / "fuzzing_report.json"
        scenario_json = reports_dir / "scenario_coverage.json"
        scenario_html = reports_dir / "scenario.html"

        scenario_md = reports_dir / "scenario_summary.md"
        sc = _safe_load_json(scenario_json)

        # Scenario coverage schema versions:
        # - newer: { observedCount, expectedCount }
        # - older: { observed, expected }
        sc_obs = None
        sc_exp = None
        if isinstance(sc, dict):
            sc_obs = sc.get("observedCount")
            if sc_obs is None:
                sc_obs = sc.get("observed")

            sc_exp = sc.get("expectedCount")
            if sc_exp is None:
                sc_exp = sc.get("expected")

            # Defensive: some legacy outputs store expected as a list of scenario ids.
            if isinstance(sc_exp, list):
                sc_exp = len(sc_exp)
            if isinstance(sc_obs, list):
                sc_obs = len(sc_obs)

        sc_cov = sc.get("coverage") if isinstance(sc, dict) else None

        started_at = str(
            run_json.get("createdAt")
            or run_json.get("startedAt")
            or rec.get("createdAt")
            or ""
        )

        rows.append(
            RunRow(
                run_id=run_id,
                work_dir=str(wd),
                harness=harness,
                target=target,
                started_at=started_at,
                status=str(run_json.get("status") or ""),
                bitmap_coverage_percent=(float(bitmap_cov) if bitmap_cov is not None else -1.0),
                queue_size=int(queue_sz or 0),
                total_crashes=int(crashes or 0),
                scenario_coverage=(float(sc_cov) if sc_cov is not None else -1.0),
                scenarios_observed=int(sc_obs or 0),
                scenarios_expected=int(sc_exp or 0),
                report_html=str(report_html) if report_html.exists() else "",
                report_json=str(report_json) if report_json.exists() else "",
                scenario_json=str(scenario_json) if scenario_json.exists() else "",
                scenario_md=str(scenario_md) if scenario_md.exists() else "",
                scenario_html=str(scenario_html) if scenario_html.exists() else "",
            )
        )

    # newest first if started_at exists; otherwise stable by run_id
    rows.sort(key=lambda r: (r.started_at or "", r.run_id), reverse=True)
    return rows
