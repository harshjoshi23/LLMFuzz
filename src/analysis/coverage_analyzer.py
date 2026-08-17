"""Coverage analyzer for AFL++ outputs.

Phase 3 component: Coverage Analyzer.

IMPORTANT:
There are multiple call sites that need coverage. The canonical AFL++ parsing
lives in `src.reporters.report_generator.parse_afl_output()`. This module is a
thin adapter that produces a lightweight dict view for agents (e.g. state
explorer) while delegating parsing to the canonical implementation.

Uncovered branches/lines require gcov/llvm-cov instrumentation and remain
best-effort placeholders.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class CoverageAnalyzer:
    def __init__(self, afl_output_dir: Path):
        self.afl_output_dir = Path(afl_output_dir)

    def analyze(self) -> Dict[str, Any]:
        """Analyze AFL output directory.

        Supports passing either:
          - the AFL run root (contains `default/fuzzer_stats`)
          - the `default` dir itself
        """

        default_dir = self._default_dir()

        try:
            from src.reporters.report_generator import parse_afl_output

            # parse_afl_output expects the AFL run *root* (the directory that contains
            # the fuzzer instance subdir, typically `default/`).
            afl_root = self.afl_output_dir
            res = parse_afl_output(str(afl_root), parameter_constraints={}, target_name="unknown")
            fuzz = getattr(res, "fuzzing_stats", {}) or {}
            cov = float(getattr(res, "coverage_percent", 0.0) or 0.0)
        except Exception as e:
            logger.warning("CoverageAnalyzer: canonical parse failed: %s", e)
            fuzz = {}
            cov = 0.0

        return {
            "coverage_percent": cov,
            "execs_done": int(fuzz.get("execs_done", 0) or 0),
            "execs_per_sec": float(fuzz.get("execs_per_sec", 0.0) or 0.0),
            "saved_crashes": int(fuzz.get("saved_crashes", 0) or 0),
            "saved_hangs": int(fuzz.get("saved_hangs", 0) or 0),
            "corpus_count": int(fuzz.get("corpus_count", 0) or 0),
            "edges_found": int(fuzz.get("edges_found", 0) or 0),
            "total_edges": int(fuzz.get("total_edges", 0) or 0),
            "raw_stats": fuzz,
            "uncovered": {
                "branches": self._extract_uncovered_branches(),
                "lines": self._extract_uncovered_lines(),
            },
        }

    def _default_dir(self) -> Path:
        d = self.afl_output_dir
        if (d / "fuzzer_stats").exists():
            return d
        if (d / "default" / "fuzzer_stats").exists():
            return d / "default"
        return d / "default"

    def _extract_uncovered_branches(self) -> List[Any]:
        return []

    def _extract_uncovered_lines(self) -> List[Any]:
        return []
