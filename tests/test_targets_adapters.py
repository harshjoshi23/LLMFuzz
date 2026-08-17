from pathlib import Path

import pytest

from src.targets_adapters import GenericExecutableHarnessAdapter, TargetAdapterError


def test_generic_adapter_validates_missing(tmp_path: Path):
    with pytest.raises(TargetAdapterError):
        GenericExecutableHarnessAdapter(harness_path=str(tmp_path / "nope")).get_harness_path()


def test_generic_adapter_ok(tmp_path: Path):
    p = tmp_path / "h"
    p.write_text("x")
    assert GenericExecutableHarnessAdapter(harness_path=str(p)).get_harness_path() == str(p)
