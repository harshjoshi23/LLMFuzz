"""Hardened AFL++ runner.

Design goals:
- Offline/mock friendly: supports dry-run mode with mocked subprocess
- Standard artifact layout: results/<run_id>/afl/<protocol>/
- Always writes a normalized run.json
- Friendly diagnostics if afl-fuzz is missing

This module is *target-agnostic*; it runs an executable harness that accepts AFL's @@ file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional, Any


@dataclass
class AflRunResult:
    protocol: str
    duration_seconds: int
    afl_present: bool
    status: str  # completed|skipped|error|dry_run
    output_dir: str
    harness_path: str
    corpus_dir: str

    crashes_found: int = 0
    queue_size: int = 0

    # AFL++ bitmap coverage (fuzzer_stats: bitmap_cvg)
    bitmap_coverage_percent: Optional[float] = None

    fuzzer_stats_path: Optional[str] = None
    error: Optional[str] = None

    # Optional line/branch coverage artifacts (gcovr/lcov/llvm-cov)
    coverage: Optional[Dict[str, Any]] = None


class AflRunner:
    def __init__(self, afl_fuzz: str = "afl-fuzz"):
        self.afl_fuzz = afl_fuzz

    def check_afl(self) -> Optional[str]:
        return shutil.which(self.afl_fuzz)

    def run(
        self,
        *,
        protocol: str,
        duration_seconds: int,
        results_root: str,
        run_id: str,
        harness_path: str,
        corpus_dir: str,
        timeout_ms: int = 1000,
        dry_run: bool = False,
        env: Optional[Dict[str, str]] = None,
        resume: bool = False,
        resume_dir: Optional[str] = None,
    ) -> AflRunResult:
        """Run AFL++ for a fixed duration.

        Resume semantics:
        - By default, each run uses a new output directory under results/<run_id>/afl/<protocol>.
        - If resume=True, AFL output directory is reused:
          - If resume_dir is provided: use it.
          - Else: use results/<run_id>/afl/<protocol>/ (same as default).

        NOTE: AFL resume requires that the output dir contains an existing session
        (e.g., default/fuzzer_stats). AFL++ will then continue mutating from the
        existing queue/state.
        """

        out_dir = Path(results_root) / run_id / "afl" / protocol
        if resume_dir is not None:
            out_dir = Path(resume_dir)

        try:
            from src.utils.blackboard import bb_event

            bb_event(
                "FuzzAgent",
                "fuzz_started",
                run_id=run_id,
                protocol=protocol,
                duration_seconds=duration_seconds,
                harness_path=harness_path,
                corpus_dir=corpus_dir,
                output_dir=str(out_dir),
                dry_run=dry_run,
            )
        except Exception:
            pass
        # Resolve to an absolute path so afl-fuzz receives an absolute -o value.
        # If we change the process cwd (we run afl in the harness dir), afl
        # will attempt to create the -o path relative to that cwd. Passing an
        # absolute path avoids "Unable to create ... No such file or directory"
        # errors where the same path is interpreted relative to a different cwd.
        out_dir = out_dir.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        afl_path = self.check_afl()
        if not afl_path:
            res = AflRunResult(
                protocol=protocol,
                duration_seconds=duration_seconds,
                afl_present=False,
                status="skipped" if dry_run else "error",
                output_dir=str(out_dir),
                harness_path=harness_path,
                corpus_dir=corpus_dir,
                error=(
                    "afl-fuzz not found in PATH. Install AFL++ or run with --skip-fuzzing/--dry-run."
                ),
            )
            self._write_run_json(res, out_dir)
            return res

        # Use AFL++ edge/branch coverage only (disable CMPLOG and avoid path-centric heuristics)
        if env is None:
            env = {}
        # Start from the current process environment so AFL and the harness
        # inherit PATH, HOME, THESIS_ARTIFACTS_DIR, etc.
        merged_env = dict(os.environ)
        merged_env.update(env)
        env = merged_env
        # Avoid setting deprecated vars that cause AFL++ to exit.
        # For our purposes, we want regular edge coverage, not cmplog-only.
        env.pop("AFL_CMPLOG_ONLY", None)
        # Do NOT disable deterministic stages by default.
        # (If you want faster fuzzing at the cost of skipping deterministic flips,
        # set AFL_DISABLE_TRIM=1 in the environment or pass env override.)
        # core_pattern on many systems starts with a pipe, which AFL treats as fatal.
        # To keep the pipeline runnable in restricted environments (WSL/CI), skip this check.
        env.setdefault("AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES", "1")
        env.setdefault("AFL_NO_AFFINITY", "1")
        env.setdefault("AFL_SKIP_CPUFREQ", "1")
        env.setdefault("AFL_SKIP_CORE_CHECK", "1")

        harness = Path(harness_path)
        if not harness.exists():
            res = AflRunResult(
                protocol=protocol,
                duration_seconds=duration_seconds,
                afl_present=True,
                status="error",
                output_dir=str(out_dir),
                harness_path=harness_path,
                corpus_dir=corpus_dir,
                error=f"Harness not found: {harness_path}",
            )
            self._write_run_json(res, out_dir)
            return res

        # Resolve corpus and harness to absolute paths so afl-fuzz receives
        # absolute -i / -o / binary arguments. afl-fuzz interprets relative
        # paths relative to its own CWD (we set cwd to the harness parent),
        # which previously caused "No such file or directory" errors.
        corpus = Path(corpus_dir)
        # check existence before resolving to keep error messages clear
        if not corpus.exists() or not any(corpus.iterdir()):
            res = AflRunResult(
                protocol=protocol,
                duration_seconds=duration_seconds,
                afl_present=True,
                status="error",
                output_dir=str(out_dir),
                harness_path=harness_path,
                corpus_dir=corpus_dir,
                error=f"Corpus dir missing or empty: {corpus_dir}",
            )
            self._write_run_json(res, out_dir)
            return res

        # now resolve to absolute paths for the afl command
        try:
            corpus = corpus.resolve()
        except Exception:
            corpus = corpus
        try:
            harness = harness.resolve()
        except Exception:
            harness = harness

        if dry_run:
            res = AflRunResult(
                protocol=protocol,
                duration_seconds=duration_seconds,
                afl_present=True,
                status="dry_run",
                output_dir=str(out_dir),
                harness_path=harness_path,
                corpus_dir=corpus_dir,
            )
            self._write_run_json(res, out_dir)
            return res

        # Ensure output directories that AFL expects exist. AFL sometimes fails
        # early if deeply nested parent folders aren't present or writable.
        try:
            (out_dir / "default").mkdir(parents=True, exist_ok=True)
            (out_dir / "default" / "queue").mkdir(parents=True, exist_ok=True)
            (out_dir / "default" / "crashes").mkdir(parents=True, exist_ok=True)
        except Exception:
            # If we cannot create them here, let afl-fuzz report the error as before,
            # but this should handle the common "No such file or directory" issue.
            pass

        cmd = [
            afl_path,
            "-D",  # enable deterministic stages (bit/byte flips, arith, known ints)
            "-i",
            str(corpus),
            "-o",
            str(out_dir),
            "-t",
            str(timeout_ms),
            "-V",
            str(duration_seconds),
        ]

        # If we are collecting gcov branch coverage, store .gcda under the build dir.
        # This only affects gcov-instrumented binaries.
        if env.get("THESIS_COVERAGE_MODE") == "gcov":
            env.setdefault("GCOV_PREFIX", str(Path(build_dir) / "gcov"))
            env.setdefault("GCOV_PREFIX_STRIP", "0")

        # Optional schedule override via env (set by svc_campaign_runner mode B).
        afl_sched = env.get("THESIS_AFL_SCHEDULE")
        if afl_sched:
            cmd[1:1] = ["-p", afl_sched]

        # Resume/continue an existing session.
        # AFL++ 4.x: use -i - to resume, or set AFL_AUTORESUME=1 with -i <corpus>.
        # -R is deprecated (was Radamsa in old versions).
        if resume and (out_dir / "default" / "fuzzer_stats").exists():
            # Existing session found → resume with -i -
            cmd[cmd.index(str(corpus))] = "-"
        # Always set AUTORESUME so AFL doesn't error if output dir already has data.
        env.setdefault("AFL_AUTORESUME", "1")

        # Use stdin-based mode by default; append @@ only if explicitly requested.
        cmd.extend(["--", str(harness)])
        if os.environ.get("THESIS_AFL_FILE_MODE", "0").strip().lower() in {"1", "true", "yes", "y"}:
            cmd.append("@@")

        # Provide a full command string for pipeline logs
        cmd_str = " ".join(cmd)

        # Ensure harness sees a per-run artifacts dir even if caller forgot.
        env.setdefault("THESIS_ARTIFACTS_DIR", str(out_dir.parent / "artifacts"))
        env.setdefault("THESIS_SCENARIO_LOG", str((out_dir.parent / "artifacts") / "scenario_events.log"))
        try:
            (out_dir.parent / "artifacts").mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(harness.parent),
                env=env,
                stdout=None,
                stderr=None,
                timeout=duration_seconds + 120,
            )
            status = "completed" if proc.returncode == 0 else "error"
            res = AflRunResult(
                protocol=protocol,
                duration_seconds=duration_seconds,
                afl_present=True,
                status=status,
                output_dir=str(out_dir),
                harness_path=harness_path,
                corpus_dir=corpus_dir,
                error=None if status == "completed" else "AFL process exited with code " + str(proc.returncode),
            )

        except subprocess.TimeoutExpired:
            res = AflRunResult(
                protocol=protocol,
                duration_seconds=duration_seconds,
                afl_present=True,
                status="error",
                output_dir=str(out_dir),
                harness_path=harness_path,
                corpus_dir=corpus_dir,
                error="AFL++ run timed out (runner timeout exceeded)",
            )

        self._postprocess(res, out_dir)
        # Optional native coverage collection (best-effort)
        try:
            from src.analysis.native_coverage import collect_native_coverage

            cov_out = out_dir.parent.parent.parent / "coverage" / protocol
            cov_mode = os.environ.get("THESIS_COVERAGE_MODE") or "auto"
            native = collect_native_coverage(
                build_dir=str(harness.parent),
                out_dir=str(cov_out),
                binaries=[str(harness)],
                sources_root=str(Path("third_party") / "mtb-mw-pctrl-svc"),
            )
            res.coverage = native.__dict__
            if isinstance(res.coverage, dict):
                res.coverage["requested_mode"] = cov_mode
        except Exception:
            res.coverage = None

        self._write_run_json(res, out_dir)

        try:
            from src.utils.blackboard import bb_event

            bb_event(
                "FuzzAgent",
                "fuzz_finished",
                run_id=run_id,
                status=res.status,
                afl_present=res.afl_present,
                output_dir=res.output_dir,
                crashes_found=res.crashes_found,
                queue_size=res.queue_size,
                fuzzer_stats_path=res.fuzzer_stats_path,
                error=res.error,
            )
        except Exception:
            pass

        return res

    def _postprocess(self, res: AflRunResult, out_dir: Path) -> None:
        # AFL++ typically writes stats under:
        #   <out_dir>/default/fuzzer_stats
        # In our layout, out_dir is results/<run_id>/afl/<protocol>, so that path exists.
        # Some wrappers/configs may write it under <out_dir>/fuzzer_stats.
        stats = out_dir / "default" / "fuzzer_stats"
        if not stats.exists():
            stats = out_dir / "fuzzer_stats"

        # Legacy layout fallback: results/<run_id>/afl/<protocol>/default/fuzzer_stats
        # but if caller passed results/<run_id>/afl (parent), try to discover fuzzer_stats.
        if not stats.exists():
            try:
                hits = list(out_dir.glob("*/default/fuzzer_stats"))
                if hits:
                    stats = hits[0]
            except Exception:
                pass
        if not stats.exists():
            try:
                hits = list(out_dir.glob("*/fuzzer_stats"))
                if hits:
                    stats = hits[0]
            except Exception:
                pass

        if stats.exists():
            res.fuzzer_stats_path = str(stats)

            # Extract bitmap coverage percent (AFL++ bitmap_cvg: e.g. "65.16%")
            try:
                for ln in stats.read_text(encoding="utf-8", errors="replace").splitlines():
                    if ln.strip().startswith("bitmap_cvg") and ":" in ln:
                        v = ln.split(":", 1)[1].strip().replace("%", "")
                        res.bitmap_coverage_percent = float(v)
                        break
            except Exception:
                # leave as None if parsing fails
                pass

        crashes_dir = out_dir / "default" / "crashes"
        if crashes_dir.exists():
            # AFL uses README.txt + id:* files
            res.crashes_found = len([p for p in crashes_dir.glob("id:*") if p.is_file()])

        queue_dir = out_dir / "default" / "queue"
        if queue_dir.exists():
            res.queue_size = len([p for p in queue_dir.glob("id:*") if p.is_file()])

    def _write_run_json(self, res: AflRunResult, out_dir: Path) -> None:
        payload = asdict(res)
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        (out_dir / "run.json").write_text(json.dumps(payload, indent=2))
