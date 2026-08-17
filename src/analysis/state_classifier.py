"""State/scenario detection (deterministic, thesis-friendly).

This module extracts *ObservedScenarios* from:
- scenario_events.log emitted by harness (preferred)
- lightweight state proxies from telemetry.jsonl (optional)

It also computes a pragmatic "state-space" metric:
- unique_state_labels: number of distinct state labels observed

This is intentionally rule-based. LLM-based classification can be added as an
optional fallback, but should not be required for the metric.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


@dataclass
class DetectionResult:
    observed_scenarios: Set[str]
    state_labels: Set[str]
    evidence: Dict[str, Any]


_SCENARIO_LINE_RX = re.compile(r"\bSCENARIO\s+(?P<id>[a-zA-Z0-9_\-\.]+)\b")


def detect_from_artifacts(artifacts_dir: Path) -> DetectionResult:
    artifacts_dir = Path(artifacts_dir)

    observed: Set[str] = set()
    state_labels: Set[str] = set()

    hits: List[Dict[str, Any]] = []

    # scenario_events.log
    sc_log = artifacts_dir / "scenario_events.log"
    if sc_log.exists():
        for ln in sc_log.read_text(errors="replace").splitlines():
            m = _SCENARIO_LINE_RX.search(ln)
            if m:
                sid = m.group("id")
                observed.add(sid)
                hits.append({"source": "scenario_events.log", "scenario_id": sid, "line": ln})

    # telemetry.jsonl (optional)
    tel = artifacts_dir / "telemetry.jsonl"
    if tel.exists():
        for ln in tel.read_text(errors="replace").splitlines():
            s = ln.strip()
            if not s:
                continue
            try:
                ev = json.loads(s)
            except Exception:
                continue
            if not isinstance(ev, dict):
                continue

            # state proxy: allow keys like "state", "mode", "sm_state"
            for k in ("state", "mode", "sm_state"):
                if k in ev and ev[k] is not None:
                    state_labels.add(str(ev[k]))

            # scenario proxy: allow explicit scenario id fields
            for k in ("scenario", "scenario_id"):
                if k in ev and isinstance(ev[k], str) and ev[k].strip():
                    observed.add(ev[k].strip())

    evidence = {
        "artifacts_dir": str(artifacts_dir),
        "hits": hits,
        "telemetry_state_labels": sorted(state_labels),
    }

    return DetectionResult(observed_scenarios=observed, state_labels=state_labels, evidence=evidence)
