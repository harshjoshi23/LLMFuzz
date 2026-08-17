"""Target adapter interfaces.

Adapters isolate target-specific details from the core framework.
The initial production baseline supports running a prebuilt AFL++ harness
binary that accepts an input file via @@.

Future adapters can support:
- per-block harness builders
- QEMU-based firmware runners
- protocol gateways, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional


class TargetAdapterError(RuntimeError):
    pass


@dataclass
class GenericExecutableHarnessAdapter:
    """Adapter for an AFL++-compatible executable harness."""

    harness_path: str
    type: Literal["prebuilt"] = "prebuilt"

    def validate(self) -> None:
        p = Path(self.harness_path)
        if not p.exists():
            raise TargetAdapterError(f"Harness not found: {self.harness_path}")
        if p.is_dir():
            raise TargetAdapterError(f"Harness path must be a file, got directory: {self.harness_path}")

    def get_harness_path(self) -> str:
        self.validate()
        return self.harness_path
