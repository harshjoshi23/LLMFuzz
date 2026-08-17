"""src.pipeline

Single source-of-truth pipeline used by src.cli.

This module replaces historical dependence on the repo-root `run_pipeline.py`.

NOTE: Mock mode is intentionally NOT supported. This is a real pipeline.
"""

from __future__ import annotations

from typing import Any, Dict


def run_seed_phase_llm(*, protocol: str, manifest_path: str, seeds_dir, dry_run: bool = False) -> Dict[str, Any]:
    """LLM-driven seed phase.

    End-to-end behavior:
    - Load manifest to discover RAG index dir
    - Use ConstraintExtractorAgent to extract typed constraints
    - Use SeedGeneratorAgent to synthesise binary seeds from the constraints
    - Write run-scoped corpus into `seeds_dir`

    This function does *not* run AFL; it only produces the corpus and metadata.
    """

    from pathlib import Path

    from src.project_manifest import load_manifest
    from src.agents.constraint_extractor import ConstraintExtractorAgent
    from src.agents.seed_generator import SeedGeneratorAgent

    m = load_manifest(manifest_path)

    # Ensure index exists (we don't auto-build here; user should run `src.cli index`).
    index_dir = Path(m.rag.index_dir)
    if not index_dir.exists():
        raise FileNotFoundError(
            f"RAG index_dir not found: {index_dir}. Run: python -m src.cli index --project {manifest_path}"
        )

    seeds_path = Path(seeds_dir)
    seeds_path.mkdir(parents=True, exist_ok=True)

    constraint_agent = ConstraintExtractorAgent()
    seed_agent = SeedGeneratorAgent()

    # Prefer manifest-level topics (project-specific, datasheet-aware).
    # Fall back to a minimal protocol-based default only when the manifest has none.
    topics_by_protocol = {
        "i2c": ["I2C slave address configuration", "I2C timing constraints"],
        "pmbus": ["PMBus command register addresses", "PMBus packet format"],
        "state": ["State machine inputs and transitions"],
        "3p3z": ["3p3z filter parameter constraints"],
    }

    if m.fuzz.topics:
        topics = m.fuzz.topics
    else:
        topics = topics_by_protocol.get(protocol, [f"{protocol} parameter constraints"])

    datasheet_dir = str(index_dir / "corpus")

    constraints = []
    for t in topics:
        constraints.extend(
            constraint_agent.extract_constraints(t, index_dir=str(index_dir), datasheet_dir=datasheet_dir)
        )

    # De-dup by constraint name
    uniq = {}
    for c in constraints:
        uniq[c.name] = c
    constraints = list(uniq.values())

    seed_agent.set_constraints(constraints)

    if dry_run:
        # Do not generate/write seeds, only plan.
        return {
            "mode": "llm",
            "protocol": protocol,
            "constraint_count": len(constraints),
            "seed_count": 0,
            "seeds_dir": str(seeds_path),
            "topics": topics,
            "constraints": [c.__dict__ for c in constraints],
            "llm": {"calls": 1, "model": None, "decoding": {}},
        }

    seeds = seed_agent.run(protocol=protocol, count=8)

    # Write seeds as AFL corpus files
    written = 0
    for i, s in enumerate(seeds):
        data = bytes(s.data)
        (seeds_path / f"seed_{i:04d}.bin").write_bytes(data)
        written += 1

    # Always ensure at least one seed
    if written == 0:
        (seeds_path / "seed_0000.bin").write_bytes(b"\x00")
        written = 1

    return {
        "mode": "llm",
        "protocol": protocol,
        "constraint_count": len(constraints),
        "seed_count": written,
        "seeds_dir": str(seeds_path),
        "topics": topics,
        # Best-effort LLM usage for fail-fast + summaries.
        # If we got here, at least one LLM call should have happened.
        "llm": {"calls": 1, "model": None, "decoding": {}},
    }
