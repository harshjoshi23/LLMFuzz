import json
from pathlib import Path

from src.afl_runner import AflRunner


def test_afl_runner_dry_run_writes_run_json(tmp_path: Path, monkeypatch):
    # Pretend AFL is installed
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/afl-fuzz")

    # Create dummy harness + corpus
    harness = tmp_path / "harness"
    harness.write_text("#!/bin/sh\nexit 0\n")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "seed.bin").write_bytes(b"\x00")

    r = AflRunner()
    res = r.run(
        protocol="i2c",
        duration_seconds=1,
        results_root=str(tmp_path),
        run_id="run_001",
        harness_path=str(harness),
        corpus_dir=str(corpus),
        dry_run=True,
    )

    out_dir = tmp_path / "run_001" / "afl" / "i2c"
    assert (out_dir / "run.json").exists()

    payload = json.loads((out_dir / "run.json").read_text())
    assert payload["status"] == "dry_run"
    assert payload["protocol"] == "i2c"


def test_afl_runner_missing_afl(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)

    harness = tmp_path / "harness"
    harness.write_text("x")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "seed.bin").write_bytes(b"\x00")

    r = AflRunner()
    res = r.run(
        protocol="i2c",
        duration_seconds=1,
        results_root=str(tmp_path),
        run_id="run_002",
        harness_path=str(harness),
        corpus_dir=str(corpus),
        dry_run=True,
    )

    assert res.status in {"skipped", "error"}
    assert (tmp_path / "run_002" / "afl" / "i2c" / "run.json").exists()
