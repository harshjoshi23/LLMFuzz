"""Scenario coverage analysis (thesis-critical).

Definitions:
- ExpectedScenarios: declared in the project manifest (single source of truth)
- ObservedScenarios: derived from execution evidence (scenario events / telemetry)

Metric:
  ScenarioCoverage = |ObservedScenarios| / |ExpectedScenarios|

Artifacts per run:
- scenario_coverage.json (machine readable)
- scenario_summary.md (human readable)
- scenario_summary.csv (optional aggregation friendly)

Evidence sources (deterministic):
- artifacts/scenario_events.log: line-based events
- artifacts/telemetry.jsonl: JSONL events

The harness (or peripheral emulator) should emit scenario events.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from src.analysis.state_classifier import detect_from_artifacts
from src.project_manifest import ProjectManifest, ScenarioSignal


@dataclass
class ScenarioCoverageResult:
    """Canonical scenario coverage schema.

    Notes on schema compatibility:
    - Lists: `observed` and `missing` are the canonical lists.
    - Counts: `observedCount` and `missingCount` are included for convenience.

    This keeps `evaluation.py`, `loop_controller.py`, and HTML report generation
    aligned, while still preserving historical fields.
    """

    schemaVersion: str
    runId: str

    expectedCount: int
    observedCount: int
    missingCount: int
    coverage: float

    expected: List[Dict[str, Any]]
    observed: List[Dict[str, Any]]
    missing: List[str]

    evidence: Dict[str, Any]


_SCHEMA_VERSION = "1.0"


def _sha256_path(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _safe_read_lines(p: Path) -> List[str]:
    if not p.exists():
        return []
    return p.read_text(errors="replace").splitlines()


def _safe_read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text(errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _match_key_value(pattern: str, obj: Dict[str, Any]) -> bool:
    # pattern format: key=value
    if "=" not in pattern:
        return False
    k, v = pattern.split("=", 1)
    k = k.strip()
    v = v.strip()
    if not k:
        return False
    return str(obj.get(k, "")) == v


def _detect_observed(
    *,
    signals: List[ScenarioSignal],
    scenario_events_lines: List[str],
    telemetry_events: List[Dict[str, Any]],
) -> Tuple[Set[str], Dict[str, Any]]:
    observed: Set[str] = set()
    evidence_hits: List[Dict[str, Any]] = []

    for sig in signals:
        if sig.type == "log_regex":
            rx = re.compile(sig.pattern)
            for ln in scenario_events_lines:
                if rx.search(ln):
                    observed.add(sig.scenario_id)
                    evidence_hits.append(
                        {"scenario_id": sig.scenario_id, "source": "scenario_events.log", "type": "log_regex", "pattern": sig.pattern, "line": ln}
                    )
                    break
        elif sig.type == "key_value":
            for ev in telemetry_events:
                if _match_key_value(sig.pattern, ev):
                    observed.add(sig.scenario_id)
                    evidence_hits.append(
                        {"scenario_id": sig.scenario_id, "source": "telemetry.jsonl", "type": "key_value", "pattern": sig.pattern, "event": ev}
                    )
                    break

    evidence: Dict[str, Any] = {
        "inputs": {
            "scenario_events_log_present": bool(scenario_events_lines),
            "telemetry_jsonl_present": bool(telemetry_events),
        },
        "hits": evidence_hits,
    }
    return observed, evidence


def compute_scenario_coverage(*, manifest: ProjectManifest, run_id: str, artifacts_dir: Path) -> ScenarioCoverageResult:
    expected_specs = manifest.scenarios.expected
    expected_ids = [s.id for s in expected_specs]

    # Primary evidence sources (line-based log + optional jsonl telemetry)
    scenario_events = _safe_read_lines(artifacts_dir / "scenario_events.log")
    # Back-compat: some harnesses write to scenario_events.log (plural) instead.
    if not scenario_events:
        scenario_events = _safe_read_lines(artifacts_dir / "scenario_events.log")
    telemetry = _safe_read_jsonl(artifacts_dir / "telemetry.jsonl")

    observed_ids, evidence = _detect_observed(
        signals=manifest.scenarios.signals,
        scenario_events_lines=scenario_events,
        telemetry_events=telemetry,
    )

    # also include generic state/telemetry detection evidence
    det = detect_from_artifacts(artifacts_dir)
    observed_ids |= set(det.observed_scenarios)
    evidence["state_classifier"] = {
        "unique_state_labels": len(det.state_labels),
        "state_labels": sorted(det.state_labels),
        "evidence": det.evidence,
    }

    expected_count = len(expected_ids)
    observed_count = len([x for x in expected_ids if x in observed_ids])
    coverage = (float(observed_count) / float(expected_count)) if expected_count else 0.0

    expected = [
        {"id": s.id, "description": s.description, "tags": list(s.tags)}
        for s in expected_specs
    ]

    observed = []
    for sid in sorted(observed_ids):
        spec = next((s for s in expected_specs if s.id == sid), None)
        observed.append({"id": sid, "description": spec.description if spec else "", "tags": list(spec.tags) if spec else []})

    missing = [sid for sid in expected_ids if sid not in observed_ids]
    missing_count = len(missing)

    # add hashes of evidence files for reproducibility
    ev_files: Dict[str, Any] = {}
    for rel in ["scenario_events.log", "telemetry.jsonl"]:
        p = artifacts_dir / rel
        if p.exists():
            ev_files[rel] = {"path": str(p), "sha256": _sha256_path(p)}

    evidence["files"] = ev_files

    return ScenarioCoverageResult(
        schemaVersion=_SCHEMA_VERSION,
        runId=run_id,
        expectedCount=expected_count,
        observedCount=observed_count,
        missingCount=missing_count,
        coverage=coverage,
        expected=expected,
        observed=observed,
        missing=missing,
        evidence=evidence,
    )


def write_scenario_artifacts(
    *,
    result: ScenarioCoverageResult,
    out_dir: Path,
    write_csv: bool = True,
) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "scenario_coverage.json"
    json_path.write_text(json.dumps(asdict(result), indent=2, sort_keys=True))

    md_path = out_dir / "scenario_summary.md"
    md_lines: List[str] = []
    md_lines.append(f"# Scenario coverage (run {result.runId})")
    md_lines.append("")
    md_lines.append(f"- Expected: {result.expectedCount}")
    md_lines.append(f"- Observed: {result.observedCount}")
    md_lines.append(f"- ScenarioCoverage: {result.coverage:.4f}")
    md_lines.append("")

    md_lines.append("## Observed scenarios")
    if not result.observed:
        md_lines.append("- (none)")
    else:
        for s in result.observed:
            desc = (s.get("description") or "").strip()
            md_lines.append(f"- `{s['id']}`{(' — ' + desc) if desc else ''}")

    md_lines.append("")
    md_lines.append("## Missing scenarios")
    if not result.missing:
        md_lines.append("- (none)")
    else:
        for sid in result.missing:
            md_lines.append(f"- `{sid}`")

    md_lines.append("")
    md_lines.append("## Evidence")
    md_lines.append("```json")
    md_lines.append(json.dumps(result.evidence, indent=2, sort_keys=True)[:20000])
    md_lines.append("```")

    md_path.write_text("\n".join(md_lines) + "\n")

    csv_path = out_dir / "scenario_summary.csv"
    if write_csv:
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["run_id", "scenario_id", "observed", "description", "tags"],
            )
            w.writeheader()
            expected_map = {s["id"]: s for s in result.expected}
            for sid, spec in expected_map.items():
                w.writerow(
                    {
                        "run_id": result.runId,
                        "scenario_id": sid,
                        "observed": 1 if sid in {o["id"] for o in result.observed} else 0,
                        "description": spec.get("description", ""),
                        "tags": ",".join(spec.get("tags", []) or []),
                    }
                )

    return {
        "scenario_coverage_json": str(json_path),
        "scenario_summary_md": str(md_path),
        "scenario_summary_csv": str(csv_path) if write_csv else "",
    }
