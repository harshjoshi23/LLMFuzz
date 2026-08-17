import json
import os
from pathlib import Path

import pytest


def test_count_tokens_basic():
    from src.utils.token_counter import count_tokens

    res = count_tokens("hello world", model="text-embedding-3-small")
    assert res.tokens > 0


def test_count_tokens_fallback():
    from src.utils.token_counter import count_tokens

    res = count_tokens("hello world", model="unknown-model-xyz")
    assert res.tokens > 0
    assert res.encoding == "cl100k_base"
    assert res.approx is True
