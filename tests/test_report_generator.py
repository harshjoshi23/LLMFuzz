import json
from pathlib import Path

from src.reporters.report_generator import ReportGenerator, FuzzingResults, CrashInfo


def test_report_generator_markdown(tmp_path: Path):
    crash_inp = tmp_path / "id:000000"
    crash_inp.write_bytes(b"\x00\x01\x02hello\xff")

    results = FuzzingResults(
        target_name="demo",
        duration_seconds=10,
        total_executions=1234,
        executions_per_second=12.3,
        coverage_percent=1.0,
        crashes=[
            CrashInfo(crash_id="id:000000", input_file=str(crash_inp), crash_type="CRASH"),
        ],
        parameter_constraints={
            "X": {"min": 0, "max": 10, "inclusive_min": True, "inclusive_max": True},
        },
    )

    rg = ReportGenerator(results)
    md = rg.generate_markdown()
    assert "# Fuzzing Report" in md
    assert "Raw Input (hex)" in md

    out_md = tmp_path / "fuzzing_report.md"
    out_json = tmp_path / "fuzzing_report.json"

    rg.save_markdown(str(out_md))
    rg.save_json(str(out_json))

    assert out_md.exists() and out_md.read_text()
    assert out_json.exists()
    payload = json.loads(out_json.read_text())
    assert payload["target"] == "demo"


