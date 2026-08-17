"""Helpers to decode AFL crash inputs into structured parameters.

This supports crash categorization: in-range vs out-of-range.

Design intent:
- Keep decoding deterministic (no LLM calls).
- Used by ReportGenerator/parse_afl_output and by AnalysisAgent prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


def _int32_le(b: bytes, off: int) -> int:
    v = int.from_bytes(b[off : off + 4], byteorder="little", signed=True)
    return v


def _uint8(b: bytes, off: int) -> int:
    return b[off]


@dataclass(frozen=True)
class Decoded3P3Z:
    cx_q23: Tuple[int, int, int, int]
    cy_q23: Tuple[int, int, int]
    scaleCx: int
    scaleCy: int
    gIn: int
    gOut: int
    out_offset: int
    limit_max: int
    limit_min: int
    input_sample: int

    def to_parameters_float(self) -> Dict[str, Any]:
        q23_scale = 1 << 23
        params: Dict[str, Any] = {}
        for i, v in enumerate(self.cx_q23):
            params[f"cx_q23[{i}]"] = v / q23_scale
        for i, v in enumerate(self.cy_q23):
            params[f"cy_q23[{i}]"] = v / q23_scale
        params.update(
            {
                "scaleCx": self.scaleCx,
                "scaleCy": self.scaleCy,
                "gIn": self.gIn,
                "gOut": self.gOut,
                "out_offset": self.out_offset,
                "limit_max": self.limit_max,
                "limit_min": self.limit_min,
                "input_sample": self.input_sample,
            }
        )
        return params


def decode_3p3z_params(data: bytes) -> Optional[Decoded3P3Z]:
    """Decode bytes according to test_results/harness_3p3z.c packing."""

    # Layout from harness_3p3z.c (packed struct):
    # int32 cx[4] (16)
    # int32 cy[3] (12) => 28
    # u8 scaleCx, u8 scaleCy, u8 gIn, u8 gOut (4) => 32
    # int32 out_offset, int32 limit_max, int32 limit_min, int32 input_sample (16) => 48 bytes
    min_size = 48
    if len(data) < min_size:
        return None

    off = 0
    cx = tuple(_int32_le(data, off + 4 * i) for i in range(4))
    off += 16
    cy = tuple(_int32_le(data, off + 4 * i) for i in range(3))
    off += 12

    scaleCx = _uint8(data, off)
    scaleCy = _uint8(data, off + 1)
    gIn = _uint8(data, off + 2)
    gOut = _uint8(data, off + 3)
    off += 4

    out_offset = _int32_le(data, off)
    limit_max = _int32_le(data, off + 4)
    limit_min = _int32_le(data, off + 8)
    input_sample = _int32_le(data, off + 12)

    return Decoded3P3Z(
        cx_q23=cx,
        cy_q23=cy,
        scaleCx=scaleCx,
        scaleCy=scaleCy,
        gIn=gIn,
        gOut=gOut,
        out_offset=out_offset,
        limit_max=limit_max,
        limit_min=limit_min,
        input_sample=input_sample,
    )
