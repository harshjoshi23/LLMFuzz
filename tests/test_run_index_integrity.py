"""Never record a success-shaped corpus digest after a failed file read."""
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from src.run_index import _sha256_dir, append_run_index


def test_complete_corpus_preserves_digest_format(tmp_path):
    (tmp_path / 'b').write_bytes(b'two')
    (tmp_path / 'a').write_bytes(b'one')
    expected = hashlib.sha256(b'a\0one\0b\0two\0').hexdigest()
    assert _sha256_dir(tmp_path) == expected


def test_unreadable_corpus_does_not_append_partial_provenance(tmp_path):
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    unreadable = corpus / 'seed.bin'
    unreadable.write_bytes(b'seed')
    index = tmp_path / 'run_index.jsonl'
    existing = b'{"runId":"earlier"}\n'
    index.write_bytes(existing)
    original = Path.read_bytes

    def read(path):
        if path == unreadable:
            raise PermissionError('fixture read denied')
        return original(path)

    with patch.object(Path, 'read_bytes', read), pytest.raises(PermissionError):
        append_run_index(repo_root=tmp_path, run_id='failed', work_dir=tmp_path,
                         target='fixture', protocol='i2c', harness_path='',
                         corpus_dir=str(corpus), afl={}, coverage={}, scenario={},
                         crashes={}, index_path=index)
    assert index.read_bytes() == existing
