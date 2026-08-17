"""Native code coverage collection (optional).

Goal
----
Provide *line/function* coverage artifacts (not just AFL edges) when the target
is built with coverage instrumentation.

Design
------
- Best-effort: if tooling isn't installed or no profraw/gcda files exist,
  returns a structured "not_run" result.
- Run-scoped: outputs under results/<run_id>/coverage/...
- Zero hardcoding: caller passes all paths.

Supported modes
---------------
1) LLVM (preferred): clang/clang++ with -fprofile-instr-generate -fcoverage-mapping
   - Produces *.profraw which is merged via llvm-profdata
   - Coverage report via llvm-cov show/export

2) GCC/gcov (fallback): gcc/g++ with --coverage
   - Produces *.gcda/*.gcno
   - Report via gcovr (recommended) or lcov/genhtml

This module only *collects* coverage from artifacts; it does not modify builds.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class NativeCoverageResult:
    status: str  # completed|not_run|error
    mode: str  # llvm|gcov
    output_dir: str
    summary: Dict[str, Any]
    artifacts: Dict[str, str]
    # Normalized metrics (when available)
    line_percent: Optional[float] = None
    branch_percent: Optional[float] = None
    function_percent: Optional[float] = None
    error: Optional[str] = None


def _run(cmd: List[str], *, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def collect_native_coverage(
    *,
    build_dir: str,
    out_dir: str,
    binaries: List[str],
    sources_root: Optional[str] = None,
) -> NativeCoverageResult:
    """Collect coverage artifacts from an instrumented build.

    Args:
      build_dir: directory where build outputs and coverage files exist
      out_dir: results/<run_id>/coverage
      binaries: list of instrumented binaries to report coverage for
      sources_root: optional root directory for sources (improves report paths)

    Returns:
      NativeCoverageResult with machine-readable summary and artifact paths.
    """

    bdir = Path(build_dir)
    odir = Path(out_dir)
    odir.mkdir(parents=True, exist_ok=True)

    llvm_cov = shutil.which("llvm-cov")
    llvm_profdata = shutil.which("llvm-profdata")
    gcovr = shutil.which("gcovr")
    lcov = shutil.which("lcov")

    # Prefer LLVM coverage if tooling exists and profraw files are present
    profraws = list(bdir.rglob("*.profraw"))
    if llvm_cov and llvm_profdata and profraws:
        merged = odir / "coverage.profdata"
        cmd = [llvm_profdata, "merge", "-sparse", "-o", str(merged)] + [str(p) for p in profraws]
        p = _run(cmd)
        if p.returncode != 0:
            return NativeCoverageResult(
                status="error",
                mode="llvm",
                output_dir=str(odir),
                summary={},
                artifacts={},
                error=f"llvm-profdata merge failed: {p.stderr.strip()}",
            )

        report_json = odir / "llvm_cov.json"
        # llvm-cov export produces JSON coverage suitable for post-processing
        export_cmd = [
            llvm_cov,
            "export",
            "-format=text",
            "-instr-profile",
            str(merged),
        ] + binaries
        if sources_root:
            export_cmd += ["-path-equivalence", f"{sources_root},{sources_root}"]

        p2 = _run(export_cmd, cwd=str(bdir))
        if p2.returncode != 0:
            return NativeCoverageResult(
                status="error",
                mode="llvm",
                output_dir=str(odir),
                summary={},
                artifacts={"profdata": str(merged)},
                error=f"llvm-cov export failed: {p2.stderr.strip()}",
            )

        report_json.write_text(p2.stdout)
        return NativeCoverageResult(
            status="completed",
            mode="llvm",
            output_dir=str(odir),
            summary={"profraw_files": len(profraws)},
            artifacts={"profdata": str(merged), "llvm_cov_export": str(report_json)},
            line_percent=None,
            branch_percent=None,
            function_percent=None,
        )

    # Fallback to gcovr if present and gcda files exist
    gcdas = list(bdir.rglob("*.gcda"))
    if gcovr and gcdas:
        report_json = odir / "gcovr.json"
        report_html = odir / "gcovr.html"

        cmd = [gcovr, "--json", str(report_json), "--html-details", str(report_html), "--root", str(sources_root or bdir)]
        p = _run(cmd, cwd=str(bdir))
        if p.returncode != 0:
            return NativeCoverageResult(
                status="error",
                mode="gcov",
                output_dir=str(odir),
                summary={},
                artifacts={},
                error=f"gcovr failed: {p.stderr.strip()}",
            )

        # parse summary if possible
        summary: Dict[str, Any] = {"gcda_files": len(gcdas)}
        line_percent = None
        branch_percent = None
        function_percent = None
        try:
            j = json.loads(report_json.read_text())
            line_percent = j.get("line_percent")
            branch_percent = j.get("branch_percent")
            function_percent = j.get("function_percent")
            summary.update({
                "line_percent": line_percent,
                "branch_percent": branch_percent,
                "function_percent": function_percent,
            })
        except Exception:
            pass

        return NativeCoverageResult(
            status="completed",
            mode="gcov",
            output_dir=str(odir),
            summary=summary,
            artifacts={"gcovr_json": str(report_json), "gcovr_html": str(report_html)},
            line_percent=line_percent,
            branch_percent=branch_percent,
            function_percent=function_percent,
        )

    # lcov-only path placeholder: keep structured result, but don't implement without tool
    if lcov and gcdas:
        return NativeCoverageResult(
            status="not_run",
            mode="gcov",
            output_dir=str(odir),
            summary={"gcda_files": len(gcdas)},
            artifacts={},
            error="lcov is present but gcovr is not; lcov/genhtml integration not implemented yet.",
        )

    return NativeCoverageResult(
        status="not_run",
        mode="llvm" if (llvm_cov or llvm_profdata) else "gcov",
        output_dir=str(odir),
        summary={
            "tools": {"llvm-cov": bool(llvm_cov), "llvm-profdata": bool(llvm_profdata), "gcovr": bool(gcovr), "lcov": bool(lcov)},
            "profraw_files": len(profraws),
            "gcda_files": len(gcdas),
        },
        artifacts={},
        error="No native coverage artifacts found (or tools missing). Build target with coverage flags to enable.",
    )
