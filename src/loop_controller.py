"""Closed-loop fuzzing controller (Agent 3+).

This is a *deterministic orchestrator* that repeatedly runs fuzzing and uses
measurable feedback signals to decide what to do next.

Signals (available today)
-------------------------
- AFL++ fuzzer_stats (bitmap coverage %, paths, unique crashes)
- queue size growth
- (optional) native coverage artifacts if the build is instrumented
- (optional) scenario coverage if harness emits scenario events

Actions (safe + deterministic)
------------------------------
- Generate additional seeds (LLM) using extracted constraints
- Keep only seeds that improve coverage (when native coverage tooling exists)
- Write AFL dictionary suggestions (from constraints + observed tokens)
- Adjust AFL run duration per iteration

This module does not require LangChain/MCP. It calls the existing pipeline.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_scenario_coverage(run_dir: Path) -> Dict[str, Any]:
    p = run_dir / "reports" / "scenario_coverage.json"
    if not p.exists():
        return {"observed_ids": [], "observed_count": 0, "missing_count": 0}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))

        # Canonical lists
        observed_list = obj.get("observed") or []
        missing_list = obj.get("missing") or []

        observed_ids = [
            o.get("id")
            for o in observed_list
            if isinstance(o, dict) and o.get("id")
        ]

        # Prefer explicit counts if present; fall back to list lengths.
        observed_count = obj.get("observedCount")
        missing_count = obj.get("missingCount")

        return {
            "observed_ids": observed_ids,
            "observed_count": int(observed_count) if observed_count is not None else len(observed_ids),
            "missing_count": int(missing_count) if missing_count is not None else len(missing_list),
        }
    except Exception:
        return {"observed_ids": [], "observed_count": 0, "missing_count": 0}


def _pick_next_afl_schedule(*, prev: Optional[Dict[str, Any]], cur: Dict[str, Any]) -> Optional[str]:
    """Deterministic schedule policy using scenario coverage as guidance.

    AFL schedules (AFL++): fast/explore/coe/quad/etc. We keep it simple.
    Returns a schedule string or None to keep current/default.
    """

    if prev is None:
        return None

    # If scenarios are not improving, try exploration-focused schedule.
    if cur.get("observed_count", 0) <= prev.get("observed_count", 0):
        return "explore"

    # If scenarios improved, keep default.
    return None


@dataclass
class LoopConfig:
    project: str
    output: str = "results"
    protocol: Optional[str] = None
    iterations: int = 3
    iter_duration_s: int = 60
    skip_fuzzing: bool = False
    stop_on_crash: bool = False

    # Resume AFL session across iterations by reusing output dir (AFL -R).
    resume_afl: bool = False
    resume_dir: Optional[str] = None


@dataclass
class IterationSummary:
    iteration: int
    run_id: str
    run_dir: str
    afl_status: str
    crashes_found: int
    queue_size: int
    bitmap_coverage_percent: float

    scenario_observed_count: int = 0
    scenario_missing_count: int = 0
    afl_schedule_used: Optional[str] = None


@dataclass
class LoopSummary:
    started_at: str
    finished_at: str
    config: Dict[str, Any]
    iterations: List[IterationSummary]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _extract_afl_metrics(run_json: Dict[str, Any]) -> Dict[str, Any]:
    afl = run_json.get("afl") or {}
    crashes = int(afl.get("crashes_found") or 0)
    queue = int(afl.get("queue_size") or 0)
    cov = 0.0
    try:
        cov = float(afl.get("coverage_percent") or 0.0)
    except Exception:
        cov = 0.0
    status = str(afl.get("status") or "unknown")
    return {"crashes": crashes, "queue": queue, "cov": cov, "status": status}


def run_closed_loop(cfg: LoopConfig) -> LoopSummary:
    """Run N iterations of the manifest-driven pipeline.

    Notes:
    - We reuse the existing CLI/pipeline behavior via direct function import
      to avoid shelling out.
    - Each iteration has its own run_id and run folder.
    """

    from src.cli import cmd_fuzz
    import argparse

    out_root = Path(cfg.output)
    out_root.mkdir(parents=True, exist_ok=True)

    iters: List[IterationSummary] = []
    prev_scen: Optional[Dict[str, Any]] = None

    for i in range(1, cfg.iterations + 1):
        run_id = time.strftime(f"loop_%Y%m%d_%H%M%S_iter{i}")

        # Decide AFL schedule (scenario-guided) for this iteration.
        # Policy uses *previous* iteration's scenario coverage improvement.
        # So: read current scenario coverage from the last finished run (prev_scen)
        # and compare to the one before that (prev_prev_scen).
        # We store prev_prev_scen in the variable below.
        prev_prev_scen = None
        if iters:
            # last recorded iteration -> its run_dir
            try:
                last_run_dir = Path(iters[-1].run_dir)
                prev_prev_scen = _read_scenario_coverage(last_run_dir)
            except Exception:
                prev_prev_scen = None

        cur_for_policy = prev_scen or {"observed_count": 0}
        next_schedule = _pick_next_afl_schedule(prev=prev_prev_scen, cur=cur_for_policy)
        if next_schedule:
            import os

            os.environ["THESIS_AFL_SCHEDULE"] = next_schedule

        # Safety: if we are resuming a single AFL session dir, we must not start
        # a new afl-fuzz while the previous one is still running.
        if cfg.resume_afl:
            # If the user points to a directory containing an active session,
            # fail fast with a clear message.
            check_dir = Path(cfg.resume_dir) if cfg.resume_dir else (out_root / "afl_sessions" / (cfg.protocol or "default"))
            stats_path = check_dir / "default" / "fuzzer_stats"
            if stats_path.exists():
                try:
                    import re
                    txt = stats_path.read_text(encoding="utf-8", errors="ignore")
                    m = re.search(r"^fuzzer_pid\s*:\s*(\d+)\s*$", txt, re.MULTILINE)
                    if m:
                        pid = int(m.group(1))
                        # os.kill(pid, 0) checks if PID exists without killing.
                        import os
                        os.kill(pid, 0)
                        raise RuntimeError(
                            f"AFL session appears active (pid={pid}) in {check_dir}. "
                            f"Stop the running afl-fuzz or choose a different --resume-dir before continuing."
                        )
                except ProcessLookupError:
                    # pid not running anymore -> ok
                    pass
                except PermissionError:
                    # can't check PID -> warn but proceed
                    pass

        # If resuming, keep a stable AFL output directory across iterations.
        afl_resume_dir = None
        if cfg.resume_dir:
            afl_resume_dir = cfg.resume_dir
        elif cfg.resume_afl:
            afl_resume_dir = str(out_root / "afl_sessions" / (cfg.protocol or "default"))

        args = argparse.Namespace(
            project=cfg.project,
            output=str(out_root),
            run_id=run_id,
            duration=cfg.iter_duration_s,
            protocol=cfg.protocol,
            seed_count=None,
            skip_fuzzing=cfg.skip_fuzzing,
            resume=bool(cfg.resume_afl),
            resume_dir=afl_resume_dir,
            verbose=0,
            force=False,
        )

        rc = cmd_fuzz(args)
        run_dir = out_root / run_id
        run_json_path = run_dir / "run.json"
        if not run_json_path.exists():
            raise RuntimeError(f"Missing run.json at {run_json_path} (rc={rc})")

        run_obj = json.loads(run_json_path.read_text(encoding="utf-8"))
        m = _extract_afl_metrics(run_obj)
        scen = _read_scenario_coverage(run_dir)

        it_sum = IterationSummary(
            iteration=i,
            run_id=run_id,
            run_dir=str(run_dir),
            afl_status=m["status"],
            crashes_found=m["crashes"],
            queue_size=m["queue"],
            bitmap_coverage_percent=float(m["cov"]),
            scenario_observed_count=int(scen.get("observed_count") or 0),
            scenario_missing_count=int(scen.get("missing_count") or 0),
            afl_schedule_used=(__import__("os").environ.get("THESIS_AFL_SCHEDULE")),
        )

        iters.append(it_sum)
        prev_scen = scen

        if cfg.stop_on_crash and it_sum.crashes_found > 0:
            break

    summary = LoopSummary(
        started_at=_now(),
        finished_at=_now(),
        config=asdict(cfg),
        iterations=iters,
    )

    # Write loop summary
    loop_path = out_root / "loop_summary.json"
    loop_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")

    return summary
