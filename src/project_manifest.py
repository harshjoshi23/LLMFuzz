"""Project manifest model + loader.

The manifest is the production-grade contract for running the fuzzing framework.
It allows reproducible runs and clear user-facing configuration.

Supported inputs:
- YAML file (recommended)

Design goals:
- Strict validation with actionable error messages
- Forward-compatible (unknown keys tolerated in nested sections)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml


class ManifestError(ValueError):
    pass


DocType = Literal["local", "confluence_export", "jira_export"]


@dataclass
class DocSource:
    type: DocType
    path: str


@dataclass
class RagConfig:
    index_dir: str = "data/vectorstore_projects/default"


@dataclass
class HarnessConfig:
    type: Literal["prebuilt", "afl_c_harness"] = "prebuilt"
    path: str = "src/harness/fuzz_i2c"
    # For type=afl_c_harness: source file to compile with afl-clang-fast.
    # If set and type is afl_c_harness, the CLI will build it before AFL runs.
    c_file: Optional[str] = None
    # Extra compile flags appended to the afl-clang-fast invocation.
    extra_cflags: List[str] = field(default_factory=list)

    # Option A harness-entrypoint selection: the HarnessAgent proposes candidates
    # and writes them here. The user selects by setting `entrypoint`.
    entrypoint: Optional[str] = None
    entrypoint_candidates: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ScenarioSignal:
    """A rule-based signal that indicates a scenario was observed.

    Types:
      - log_regex: match against scenario_events.log lines
      - key_value: match against JSONL telemetry events (key=value exact match)

    Notes:
    - Keep this deterministic (no LLM) for thesis defensibility.
    """

    type: Literal["log_regex", "key_value"]
    pattern: str
    scenario_id: str


@dataclass
class ScenarioSpec:
    id: str
    description: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class ScenarioConfig:
    """Scenario coverage config (ExpectedScenarios + detection signals)."""

    expected: List[ScenarioSpec] = field(default_factory=list)
    signals: List[ScenarioSignal] = field(default_factory=list)


@dataclass
class FuzzConfig:
    protocol: Literal["i2c", "pmbus", "3p3z"] = "i2c"
    duration_seconds: int = 300
    seed_count: int = 50
    harness: HarnessConfig = field(default_factory=HarnessConfig)

    # Input framing for stateful multi-transaction harnesses.
    # - raw: a single blob (classic AFL)
    # - len16le_frames: repeated [u16_le len][payload] frames; len==0 terminates
    framing: Literal["raw", "len16le_frames"] = "raw"

    # Project-specific RAG topics used by ConstraintExtractor.
    # If empty, pipeline falls back to a protocol-based default mapping.
    topics: List[str] = field(default_factory=list)


@dataclass
class ProjectConfig:
    name: str
    target_path: str


@dataclass
class DiscoveryConfig:
    enabled: bool = True

    # Best-effort time budget for discovery-related work (heuristics, scanning).
    # The pipeline should keep discovery bounded.
    budget_seconds: int = 120

    # If true, pipeline may fall back to a baseline harness stub when discovery fails.
    allow_baseline_harness_fallback: bool = True


@dataclass
class Agent3ExplorerConfig:
    enabled: bool = True

    # If user does not set a time, we do periodic reviews.
    review_interval_seconds: int = 30 * 60


@dataclass
class ProjectManifest:
    schema_version: str = "1.0"
    mode: Literal["starter", "expert"] = "starter"

    project: ProjectConfig = field(default_factory=lambda: ProjectConfig(name="", target_path=""))
    docs: List[DocSource] = field(default_factory=list)
    rag: RagConfig = field(default_factory=RagConfig)
    fuzz: FuzzConfig = field(default_factory=FuzzConfig)
    scenarios: ScenarioConfig = field(default_factory=ScenarioConfig)

    # Generic repo support
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)

    # Non-thesis operational agent (optional): periodic repo review / health checks
    agent3_explorer: Agent3ExplorerConfig = field(default_factory=Agent3ExplorerConfig)


def load_manifest(path: str) -> ProjectManifest:
    p = Path(path)
    if not p.exists():
        raise ManifestError(f"project manifest not found: {path}")

    data = yaml.safe_load(p.read_text()) or {}

    schema_version = str(data.get("schemaVersion", data.get("schema_version", "1.0")))
    mode = str(data.get("mode", "starter")).strip()
    if mode not in {"starter", "expert"}:
        raise ManifestError("manifest.mode must be 'starter' or 'expert'")

    if "project" not in data:
        raise ManifestError("manifest missing required key: project")

    proj = data["project"]
    if not isinstance(proj, dict):
        raise ManifestError("manifest.project must be an object")

    name = proj.get("name")
    target_path = proj.get("target_path")
    if not name or not target_path:
        raise ManifestError("manifest.project must include name and target_path")

    docs_raw = data.get("docs", []) or []
    docs: List[DocSource] = []
    if not isinstance(docs_raw, list):
        raise ManifestError("manifest.docs must be a list")

    for i, d in enumerate(docs_raw):
        if not isinstance(d, dict):
            raise ManifestError(f"manifest.docs[{i}] must be an object")
        t = d.get("type")
        dp = d.get("path")
        if t not in {"local", "confluence_export", "jira_export"}:
            raise ManifestError(f"manifest.docs[{i}].type invalid: {t}")
        if not dp:
            raise ManifestError(f"manifest.docs[{i}].path missing")
        docs.append(DocSource(type=t, path=str(dp)))

    rag_cfg = data.get("rag", {}) or {}
    if not isinstance(rag_cfg, dict):
        raise ManifestError("manifest.rag must be an object")

    fuzz_cfg = data.get("fuzz", {}) or {}
    if not isinstance(fuzz_cfg, dict):
        raise ManifestError("manifest.fuzz must be an object")

    harness_cfg = fuzz_cfg.get("harness", {}) or {}
    if not isinstance(harness_cfg, dict):
        raise ManifestError("manifest.fuzz.harness must be an object")

    # discovery
    discovery_cfg = data.get("discovery", {}) or {}
    if not isinstance(discovery_cfg, dict):
        raise ManifestError("manifest.discovery must be an object")

    # optional operational agent3 (not thesis-critical)
    agent3_cfg = data.get("agent3Explorer", data.get("agent3_explorer", {})) or {}
    if not isinstance(agent3_cfg, dict):
        raise ManifestError("manifest.agent3Explorer must be an object")

    # scenarios
    scenarios_cfg = data.get("scenarios", {}) or {}
    if not isinstance(scenarios_cfg, dict):
        raise ManifestError("manifest.scenarios must be an object")

    expected_raw = scenarios_cfg.get("expected", []) or []
    if not isinstance(expected_raw, list):
        raise ManifestError("manifest.scenarios.expected must be a list")

    signals_raw = scenarios_cfg.get("signals", []) or []
    if not isinstance(signals_raw, list):
        raise ManifestError("manifest.scenarios.signals must be a list")

    expected: List[ScenarioSpec] = []
    for i, s in enumerate(expected_raw):
        if not isinstance(s, dict):
            raise ManifestError(f"manifest.scenarios.expected[{i}] must be an object")
        sid = s.get("id")
        if not isinstance(sid, str) or not sid.strip():
            raise ManifestError(f"manifest.scenarios.expected[{i}].id missing/empty")
        tags = s.get("tags", []) or []
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            raise ManifestError(f"manifest.scenarios.expected[{i}].tags must be a list[str]")
        expected.append(
            ScenarioSpec(
                id=sid.strip(),
                description=str(s.get("description", "")),
                tags=[t.strip() for t in tags if t.strip()],
            )
        )

    signals: List[ScenarioSignal] = []
    for i, sig in enumerate(signals_raw):
        if not isinstance(sig, dict):
            raise ManifestError(f"manifest.scenarios.signals[{i}] must be an object")
        st = sig.get("type")
        if st not in {"log_regex", "key_value"}:
            raise ManifestError(f"manifest.scenarios.signals[{i}].type invalid: {st}")
        pat = sig.get("pattern")
        if not isinstance(pat, str) or not pat.strip():
            raise ManifestError(f"manifest.scenarios.signals[{i}].pattern missing/empty")
        scenario_id = sig.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ManifestError(f"manifest.scenarios.signals[{i}].scenario_id missing/empty")
        signals.append(ScenarioSignal(type=st, pattern=pat, scenario_id=scenario_id.strip()))

    manifest = ProjectManifest(
        schema_version=schema_version,
        mode=mode,  # starter/expert
        project=ProjectConfig(name=str(name), target_path=str(target_path)),
        docs=docs,
        rag=RagConfig(index_dir=str(rag_cfg.get("index_dir", RagConfig.index_dir))),
        fuzz=FuzzConfig(
            protocol=str(fuzz_cfg.get("protocol", "i2c")),
            duration_seconds=int(fuzz_cfg.get("duration_seconds", 300)),
            seed_count=int(fuzz_cfg.get("seed_count", 50)),
            framing=str(fuzz_cfg.get("framing", "raw")),
            topics=[str(t) for t in (fuzz_cfg.get("topics", []) or []) if str(t).strip()],
            harness=HarnessConfig(
                type=str(harness_cfg.get("type", "prebuilt")),
                path=str(harness_cfg.get("path", "src/harness/fuzz_i2c")),
                c_file=(
                    str(harness_cfg.get("c_file")).strip()
                    if harness_cfg.get("c_file") is not None
                    else None
                ),
                extra_cflags=[str(x) for x in (harness_cfg.get("extra_cflags", []) or [])],
                entrypoint=(
                    str(harness_cfg.get("entrypoint")).strip()
                    if harness_cfg.get("entrypoint") is not None
                    else None
                ),
                entrypoint_candidates=list(harness_cfg.get("entrypoint_candidates", []) or []),
            ),
        ),
        scenarios=ScenarioConfig(expected=expected, signals=signals),
        discovery=DiscoveryConfig(
            enabled=bool(discovery_cfg.get("enabled", True)),
            budget_seconds=int(discovery_cfg.get("budget_seconds", 120)),
            allow_baseline_harness_fallback=bool(discovery_cfg.get("allow_baseline_harness_fallback", True)),
        ),
        agent3_explorer=Agent3ExplorerConfig(
            enabled=bool(agent3_cfg.get("enabled", True)),
            review_interval_seconds=int(agent3_cfg.get("review_interval_seconds", 30 * 60)),
        ),
    )

    return manifest
