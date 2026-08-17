import json
from pathlib import Path

import pytest


def test_dry_run_schema(tmp_path, monkeypatch):
    # Arrange: fake project manifest by using an existing project file but overriding index dir
    project_path = Path("projects/infineon-dc-optimizer.project.yaml")
    assert project_path.exists(), "fixture project manifest missing"

    # Redirect results output
    out_root = tmp_path / "results"
    out_root.mkdir()

    # Monkeypatch cmd_index to no-op (we are not building a real index in unit test)
    # Instead, we create a minimal vectorstore on disk matching expected layout.
    pytest.importorskip("faiss", reason="faiss-cpu is required for VectorStore dry-run tests")
    from src.rag_pipeline.vectorstore import VectorStore

    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "corpus").mkdir()

    # Minimal FAISS store: use 8-dim and 2 dummy chunks, mock embedder via deterministic vectors.
    # We avoid touching GPT4IFX.
    import numpy as np

    vs = VectorStore(embedding_dim=8, index_type="flat")
    chunks = [
        {"chunk_id": "c1", "document": "a.txt", "page": 1, "section": "s", "text": "foo", "tokens": 1},
        {"chunk_id": "c2", "document": "b.txt", "page": 1, "section": "s", "text": "bar", "tokens": 1},
    ]

    class FakeClient:
        def embed_text(self, text: str, model: str = "text-embedding-3-small"):
            # stable 8-dim vector
            v = np.zeros((8,), dtype=np.float32)
            v[0] = float(len(text) % 7)
            return v.tolist()

    vs.add_chunks(chunks, client=FakeClient(), embedding_model="text-embedding-3-small")
    vs.save(str(index_dir))

    # Patch manifest load so dry-run uses our index dir
    from src import project_manifest as pm

    orig_load = pm.load_manifest

    def load_manifest_patched(p):
        m = orig_load(p)
        m.rag.index_dir = str(index_dir)
        return m

    monkeypatch.setattr(pm, "load_manifest", load_manifest_patched)

    # Patch create_client/model selection so retrieval doesn't call network
    from src import dry_run as dr

    monkeypatch.setattr(dr, "create_client", lambda: FakeClient())

    class Choice:
        chat_primary = "gpt-4o"
        embedding = "text-embedding-3-small"

    # Fake client doesn't implement list_models; dry_run should fall back cleanly.

    # Act
    out_path = dr.run_cli_dry_run(
        project_path=str(project_path),
        protocol="i2c",
        output_root=str(out_root),
        run_id="dryrun_test",
        show_rag_content=False,
    )

    # Assert
    assert out_path.exists()
    obj = json.loads(out_path.read_text(encoding="utf-8"))
    for k in [
        "schema_version",
        "run_id",
        "project",
        "protocol",
        "manifest_path",
        "index_dir",
        "embedding",
        "vectorstore",
        "constraint_extractor",
        "seed_generator",
        "timings_ms",
        "ran_at_utc",
        "show_rag_content",
        "afl_invoked",
        "harness_built",
    ]:
        assert k in obj

    assert obj["afl_invoked"] is False
    assert obj["harness_built"] is False

    # Dry-run must always provide a non-empty constraint list for downstream tooling.
    assert obj["constraint_extractor"]["constraints_returned"] is not None
    assert int(obj["constraint_extractor"]["constraints_returned"]) > 0
