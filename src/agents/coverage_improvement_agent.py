"""CoverageImprovementAgent

Purpose
-------
Provide *best-effort* guidance to improve coverage after (or during) a fuzzing run.

This agent is intentionally offline-friendly:
- It does NOT require gcov/llvm-cov to be present.
- It reads what we already have (AFL++ fuzzer_stats + directory structure).
- If optional tooling is present (gcovr/lcov/llvm-cov), it can recommend commands,
  but it will not fail the pipeline if they are missing.

Outputs
-------
A JSON-serializable dict containing:
- summary: high-level suggestions
- afl: key stats extracted from AFL output
- recommendations: concrete next steps (AFL knobs, seed scheduling, build flags)

NOTE
----
This file was missing earlier; it is part of the TODO list to make the agent set
complete and honest.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CoverageImprovementResult:
    protocol: str
    afl_output_dir: str
    coverage_percent: float
    crashes_found: int
    queue_size: int
    recommendations: List[Dict[str, Any]]
    notes: List[str]


class CoverageImprovementAgent:
    """Heuristic coverage improvement agent.

    This is NOT an LLM-based agent; it is deterministic so it can run in offline mode.
    """

    def analyze(
        self,
        *,
        protocol: str,
        afl_output_dir: str,
        harness_path: Optional[str] = None,
        target_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        afl_dir = Path(afl_output_dir)

        from src.analysis.coverage_analyzer import CoverageAnalyzer

        cov = CoverageAnalyzer(afl_dir).analyze()
        stats = cov.get("afl", {}).get("stats", {})
        coverage_percent = float(cov.get("coverage_percent", 0.0) or 0.0)

        # Best-effort read of crash/queue counts if present
        crashes_found = 0
        queue_size = 0
        try:
            crashes_found = int(stats.get("saved_crashes", 0) or 0)
        except Exception:
            crashes_found = 0
        try:
            queue_size = int(stats.get("queued_paths", 0) or 0)
        except Exception:
            queue_size = 0

        recos: List[Dict[str, Any]] = []
        notes: List[str] = []

        # AFL knobs (generic)
        recos.append(
            {
                "category": "afl_knobs",
                "title": "Try longer time and higher exec/s",
                "details": [
                    "Increase duration (more time finds more paths).",
                    "Ensure harness is fast; avoid sleeps/IO.",
                    "Prefer persistent mode where possible.",
                ],
            }
        )

        # Seed scheduling suggestions
        recos.append(
            {
                "category": "seeds",
                "title": "Seed scheduling ideas",
                "details": [
                    "Ensure you have both boundary values and typical in-range values.",
                    "Add a few structurally valid messages (correct CRC/length/checksum if used).",
                    "If the protocol has state, include short sequences, not only single messages.",
                ],
            }
        )

        # If coverage is low, suggest dictionary / tokens
        if coverage_percent < 5.0:
            recos.append(
                {
                    "category": "afl_dictionary",
                    "title": "Add an AFL dictionary of protocol tokens",
                    "details": [
                        "Provide known command bytes/opcodes/addresses as tokens.",
                        "This often boosts early coverage drastically.",
                    ],
                }
            )

        # Optional tooling detection
        tooling = {
            "gcovr": shutil.which("gcovr"),
            "lcov": shutil.which("lcov"),
            "genhtml": shutil.which("genhtml"),
            "llvm-cov": shutil.which("llvm-cov"),
        }

        if any(tooling.values()):
            recos.append(
                {
                    "category": "line_coverage",
                    "title": "Generate line coverage reports (optional)",
                    "details": [
                        "If you build the harness/target with coverage flags, you can generate line coverage.",
                        "Detected tools: " + ", ".join([k for k, v in tooling.items() if v])
                        + ("." if any(tooling.values()) else "."),
                    ],
                    "commands": [
                        "# gcc/gcov style (example)",
                        "# CFLAGS: -O0 -g --coverage   (or -fprofile-arcs -ftest-coverage)",
                        "# run fuzz for a bit, then:",
                        "gcovr -r <repo_root> --html --html-details -o coverage.html",
                        "",
                        "# clang/llvm-cov style (example)",
                        "# CFLAGS: -O0 -g -fprofile-instr-generate -fcoverage-mapping",
                        "llvm-profdata merge -sparse default.profraw -o default.profdata",
                        "llvm-cov show <binary> -instr-profile=default.profdata > coverage.txt",
                    ],
                }
            )
        else:
            notes.append(
                "No gcovr/lcov/llvm-cov detected; line/branch gap analysis remains best-effort."
            )

        # Harness hints
        if harness_path:
            recos.append(
                {
                    "category": "harness",
                    "title": "Harden harness error handling",
                    "details": [
                        "Return quickly on invalid inputs (fast rejects improve exec/s).",
                        "Prefer deterministic parsing; avoid global state where possible.",
                        "Emit scenario evidence into THESIS_ARTIFACTS_DIR if applicable.",
                    ],
                    "harness_path": harness_path,
                }
            )

        if target_path:
            recos.append(
                {
                    "category": "build",
                    "title": "Use sanitizers for better bug signal",
                    "details": [
                        "ASan/UBSan improves crash quality and deduping.",
                        "Keep -O1/-O0 for debuggability; ensure symbols are present.",
                    ],
                    "target_path": target_path,
                }
            )

        res = CoverageImprovementResult(
            protocol=protocol,
            afl_output_dir=str(afl_dir),
            coverage_percent=coverage_percent,
            crashes_found=crashes_found,
            queue_size=queue_size,
            recommendations=recos,
            notes=notes,
        )

        return asdict(res)
