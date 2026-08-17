"""Evaluation harness (repeatable trials + metrics export).

Goal:
- Make the thesis evaluation repeatable and exportable.
- Keep this deterministic and repo-agnostic.

This runs the existing pipeline multiple times and writes:
- results/evaluation_<timestamp>.json
- results/evaluation_<timestamp>.csv

Note:
- We do not attempt to eliminate all sources of nondeterminism (AFL is stochastic),
  but we record key run metadata and per-trial metrics.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TrialMetrics:
    trial: int
    run_id: str
    run_dir: str
    rc: int

    afl_coverage_percent: float = 0.0
    afl_queue_size: int = 0
    afl_crashes_found: int = 0

    scenario_observed_count: int = 0
    scenario_missing_count: int = 0

    native_line_percent: Optional[float] = None
    native_branch_percent: Optional[float] = None
    native_function_percent: Optional[float] = None


@dataclass
class EvaluationResult:
    started_at: str
    finished_at: str
    project: str
    protocol: Optional[str]
    duration_s: int
    trials: int
    results_dir: str
    trials_metrics: List[TrialMetrics]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _safe_int(x: Any) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def run_evaluation(
    *,
    project: str,
    output: str,
    protocol: Optional[str],
    duration_s: int,
    trials: int,
    skip_fuzzing: bool = False,
) -> EvaluationResult:
    from src.cli import cmd_fuzz
    import argparse

    out_root = Path(output)
    out_root.mkdir(parents=True, exist_ok=True)

    trial_rows: List[TrialMetrics] = []

    for t in range(1, trials + 1):
        run_id = time.strftime(f"eval_%Y%m%d_%H%M%S_t{t}")

        args = argparse.Namespace(
            project=project,
            output=str(out_root),
            run_id=run_id,
            duration=duration_s,
            protocol=protocol,
            seed_count=None,
            skip_fuzzing=skip_fuzzing,
            resume=False,
            resume_dir=None,
            verbose=0,
            force=False,
        )

        rc = int(cmd_fuzz(args))
        run_dir = out_root / run_id
        run_json = run_dir / "run.json"

        tm = TrialMetrics(trial=t, run_id=run_id, run_dir=str(run_dir), rc=rc)

        if run_json.exists():
            obj = _read_json(run_json)
            extras = obj.get("extras") or {}

            afl = extras.get("afl") or {}
            tm.afl_coverage_percent = _safe_float(afl.get("coverage_percent"))
            tm.afl_queue_size = _safe_int(afl.get("queue_size"))
            tm.afl_crashes_found = _safe_int(afl.get("crashes_found"))

            # Scenario coverage (from emitted report artifact)
            sc_path = run_dir / "reports" / "scenario_coverage.json"
            if sc_path.exists():
                sc = _read_json(sc_path)
                tm.scenario_observed_count = _safe_int(sc.get("observedCount"))
                tm.scenario_missing_count = _safe_int(sc.get("missingCount"))

            cov = extras.get("coverage") or {}
            native = (cov.get("native") or {})
            tm.native_line_percent = native.get("line_percent")
            tm.native_branch_percent = native.get("branch_percent")
            tm.native_function_percent = native.get("function_percent")

        trial_rows.append(tm)

    res = EvaluationResult(
        started_at=_now(),
        finished_at=_now(),
        project=project,
        protocol=protocol,
        duration_s=int(duration_s),
        trials=int(trials),
        results_dir=str(out_root),
        trials_metrics=trial_rows,
    )

    ts = time.strftime("%Y%m%d_%H%M%S")
    json_out = out_root / f"evaluation_{ts}.json"
    csv_out = out_root / f"evaluation_{ts}.csv"

    json_out.write_text(json.dumps(asdict(res), indent=2), encoding="utf-8")

    with csv_out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(trial_rows[0]).keys()) if trial_rows else [])
        if trial_rows:
            w.writeheader()
            for r in trial_rows:
                w.writerow(asdict(r))

    return res
