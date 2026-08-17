from pathlib import Path

from src.docs_ingestor import DocsIngestor


def test_docs_ingestor_copies_files(tmp_path: Path):
    srcdir = tmp_path / "src"
    srcdir.mkdir()
    (srcdir / "a.txt").write_text("hello")
    (srcdir / "b.md").write_text("# md")

    out = tmp_path / "corpus"

    ing = DocsIngestor(project_root=str(tmp_path))
    res = ing.ingest(sources=[str(srcdir)], corpus_dir=str(out))

    assert res.files_copied == 2
    assert (out / "a.txt").exists()
    assert (out / "b.md").exists()
