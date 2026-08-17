import pytest

from src.project_manifest import load_manifest, ManifestError


def test_load_manifest_ok(tmp_path):
    p = tmp_path / "project.yaml"
    p.write_text(
        """
project:
  name: demo
  target_path: .
docs:
  - type: local
    path: data/datasheets
rag:
  index_dir: data/vectorstore_projects/demo
fuzz:
  protocol: i2c
  duration_seconds: 10
  seed_count: 3
  harness:
    type: prebuilt
    path: src/harness/fuzz_i2c
""".strip()
    )

    m = load_manifest(str(p))
    assert m.project.name == "demo"
    assert m.fuzz.protocol == "i2c"


def test_load_manifest_missing_project(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("docs: []")
    with pytest.raises(ManifestError):
        load_manifest(str(p))
