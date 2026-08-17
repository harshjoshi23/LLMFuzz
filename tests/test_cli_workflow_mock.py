import json
from pathlib import Path


import pytest


@pytest.mark.skip(reason="Mock mode removed; CLI is real-only")
def test_cli_fuzz_mock_mode_writes_run_json(tmp_path: Path):
    # Create project
    proj = tmp_path / "proj"
    proj.mkdir()

    # Harness path must exist for adapter validation
    harness = tmp_path / "harness"
    harness.write_text("x")

    # Create corpus so AflRunner can validate (dry-run)
    corpus = Path("data/corpus/i2c")
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "seed.bin").write_bytes(b"\x00")

    manifest = tmp_path / "project.yaml"
    manifest.write_text(
        f"""
project:
  name: demo
  target_path: {proj}

docs: []

rag:
  index_dir: {tmp_path}/index

fuzz:
  protocol: i2c
  duration_seconds: 1
  seed_count: 1
  harness:
    type: prebuilt
    path: {harness}
""".strip()
    )

    from src.cli import main

    out_root = tmp_path / "results"
    rc = main([
        "fuzz",
        "--project",
        str(manifest),
        "--output",
        str(out_root),
        "--run-id",
        "run_001",
        "--skip-fuzzing",
        "--mock-llm",
    ])
    assert rc == 0

    run_json = out_root / "run_001" / "run.json"
    assert run_json.exists()
    payload = json.loads(run_json.read_text())
    assert "afl" in payload
