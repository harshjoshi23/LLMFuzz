"""Template-driven structured input models.

This module enables block-agnostic fuzzing input models by loading a YAML template
that describes the byte layout and numeric domains.

Key features:
- Encode/decode using explicit offsets/sizes and types
- Q fixed-point support (q_fixed32)
- Range validation in the *decoded* domain (e.g., Q23 -> float)
- Clamp support for selected fields

Templates live at: input_models/templates/<block>.yaml
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import math


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    offset: int
    size: int
    q: Optional[int] = None
    min: Optional[float] = None
    max: Optional[float] = None
    clamp: bool = False
    description: str = ""


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    record_size_bytes: int
    endianness: str
    fields: Tuple[FieldSpec, ...]
    source_path: str


class TemplateError(ValueError):
    pass


def _project_root() -> Path:
    # src/ -> project root
    return Path(__file__).resolve().parents[1]


def template_path_for_block(block: str) -> Path:
    p = _project_root() / "input_models" / "templates" / f"{block}.yaml"
    return p


def load_template(block: str) -> TemplateSpec:
    import yaml

    p = template_path_for_block(block)
    if not p.exists():
        raise FileNotFoundError(str(p))

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TemplateError(f"Template root must be a mapping: {p}")

    name = str(data.get("name") or block)
    record_size_bytes = int(data.get("record_size_bytes"))
    endianness = str(data.get("endianness") or "little").lower()
    if endianness not in {"little", "big"}:
        raise TemplateError(f"Unsupported endianness={endianness} in {p}")

    fields_raw = data.get("fields")
    if not isinstance(fields_raw, list) or not fields_raw:
        raise TemplateError(f"Template must have non-empty fields list: {p}")

    fields: List[FieldSpec] = []
    for i, fr in enumerate(fields_raw):
        if not isinstance(fr, dict):
            raise TemplateError(f"fields[{i}] must be a mapping in {p}")

        fs = FieldSpec(
            name=str(fr.get("name")),
            type=str(fr.get("type")),
            offset=int(fr.get("offset")),
            size=int(fr.get("size")),
            q=(int(fr["q"]) if fr.get("q") is not None else None),
            min=(float(fr["min"]) if fr.get("min") is not None else None),
            max=(float(fr["max"]) if fr.get("max") is not None else None),
            clamp=bool(fr.get("clamp", False)),
            description=str(fr.get("description") or ""),
        )

        _validate_field_spec(fs, template_path=str(p))
        fields.append(fs)

    _validate_no_overlap(fields, record_size_bytes, template_path=str(p))

    return TemplateSpec(
        name=name,
        record_size_bytes=record_size_bytes,
        endianness=endianness,
        fields=tuple(fields),
        source_path=str(p),
    )


def _validate_field_spec(fs: FieldSpec, *, template_path: str) -> None:
    if not fs.name:
        raise TemplateError(f"Field missing name in {template_path}")

    allowed = {"int32", "uint32", "uint8", "q_fixed32", "float32"}
    if fs.type not in allowed:
        raise TemplateError(f"Unsupported field type={fs.type} for {fs.name} in {template_path}")

    expected_size = {
        "int32": 4,
        "uint32": 4,
        "q_fixed32": 4,
        "float32": 4,
        "uint8": 1,
    }[fs.type]
    if fs.size != expected_size:
        raise TemplateError(f"Field {fs.name} size={fs.size} must be {expected_size} for type={fs.type} in {template_path}")

    if fs.offset < 0:
        raise TemplateError(f"Field {fs.name} has negative offset in {template_path}")

    if fs.type == "q_fixed32" and fs.q is None:
        raise TemplateError(f"Field {fs.name} type=q_fixed32 requires q in {template_path}")


def _validate_no_overlap(fields: List[FieldSpec], record_size_bytes: int, *, template_path: str) -> None:
    used = [False] * record_size_bytes
    for fs in fields:
        if fs.offset + fs.size > record_size_bytes:
            raise TemplateError(f"Field {fs.name} overruns record_size_bytes in {template_path}")
        for off in range(fs.offset, fs.offset + fs.size):
            if used[off]:
                raise TemplateError(f"Field overlap at byte offset {off} for {fs.name} in {template_path}")
            used[off] = True


def validate_raw_bytes_length(data: bytes, template: TemplateSpec) -> bool:
    return len(data) >= template.record_size_bytes


def decode_bytes(data: bytes, template: TemplateSpec) -> Optional[Dict[str, Any]]:
    if not validate_raw_bytes_length(data, template):
        return None

    out: Dict[str, Any] = {}
    for fs in template.fields:
        raw = data[fs.offset : fs.offset + fs.size]
        out[fs.name] = _decode_field(raw, fs, template.endianness)
    return out


def encode_params(params: Dict[str, Any], template: TemplateSpec) -> bytes:
    buf = bytearray(b"\x00" * template.record_size_bytes)
    for fs in template.fields:
        raw = _encode_field(params.get(fs.name), fs, template.endianness)
        buf[fs.offset : fs.offset + fs.size] = raw
    return bytes(buf)


def validate_ranges(params: Dict[str, Any], template: TemplateSpec) -> bool:
    """Validate in the *decoded* domain.

    - q_fixed32 fields are floats (decoded), checked against float min/max
    - ints are checked against min/max (treated as numeric)
    """

    for fs in template.fields:
        v = params.get(fs.name)

        # Missing values are allowed only if min/max are unspecified.
        if v is None:
            if fs.min is None and fs.max is None:
                continue
            return False

        if fs.type == "q_fixed32":
            try:
                vf = float(v)
            except Exception:
                return False
            if not math.isfinite(vf):
                return False
            if fs.min is not None and vf < float(fs.min) - 1e-12:
                return False
            if fs.max is not None and vf > float(fs.max) + 1e-12:
                return False

        elif fs.type in {"int32", "uint32", "uint8"}:
            try:
                vi = int(v)
            except Exception:
                return False
            if fs.type == "uint8" and (vi < 0 or vi > 255):
                return False
            if fs.type == "uint32" and (vi < 0 or vi > 2**32 - 1):
                return False
            if fs.type == "int32" and (vi < -(2**31) or vi > 2**31 - 1):
                return False
            if fs.min is not None and vi < int(fs.min):
                return False
            if fs.max is not None and vi > int(fs.max):
                return False

        elif fs.type == "float32":
            try:
                vf = float(v)
            except Exception:
                return False
            if not math.isfinite(vf):
                return False
            if fs.min is not None and vf < float(fs.min) - 1e-12:
                return False
            if fs.max is not None and vf > float(fs.max) + 1e-12:
                return False

    return True


def clamp_params(params: Dict[str, Any], template: TemplateSpec) -> Dict[str, Any]:
    out = dict(params)
    for fs in template.fields:
        if not fs.clamp:
            continue
        if fs.name not in out:
            continue

        if fs.type == "q_fixed32" or fs.type == "float32":
            try:
                vf = float(out.get(fs.name))
            except Exception:
                vf = 0.0
            if fs.min is not None:
                vf = max(float(fs.min), vf)
            if fs.max is not None:
                vf = min(float(fs.max), vf)
            out[fs.name] = vf

        elif fs.type in {"int32", "uint32", "uint8"}:
            try:
                vi = int(out.get(fs.name))
            except Exception:
                vi = 0
            # intrinsic range
            if fs.type == "uint8":
                vi = max(0, min(255, vi))
            elif fs.type == "uint32":
                vi = max(0, min(2**32 - 1, vi))
            elif fs.type == "int32":
                vi = max(-(2**31), min(2**31 - 1, vi))
            if fs.min is not None:
                vi = max(int(fs.min), vi)
            if fs.max is not None:
                vi = min(int(fs.max), vi)
            out[fs.name] = vi

    return out


def roundtrip_close(a: Dict[str, Any], b: Dict[str, Any], template: TemplateSpec, *, q_tol_lsb: int = 1) -> bool:
    """Check decode(encode(a)) ~= a.

    For q_fixed32, the true quantization is 1/(2^q). We accept +/- q_tol_lsb LSB.
    """

    for fs in template.fields:
        if fs.name not in a or fs.name not in b:
            return False

        if fs.type == "q_fixed32":
            try:
                fa = float(a[fs.name])
                fb = float(b[fs.name])
            except Exception:
                return False
            q = int(fs.q or 0)
            tol = q_tol_lsb / float(2**q)
            if abs(fa - fb) > tol + 1e-15:
                return False
        else:
            if int(a[fs.name]) != int(b[fs.name]):
                return False

    return True


def _decode_field(raw: bytes, fs: FieldSpec, endianness: str) -> Any:
    byteorder = endianness

    if fs.type == "uint8":
        return int(raw[0])

    if fs.type == "int32":
        return int.from_bytes(raw, byteorder=byteorder, signed=True)

    if fs.type == "uint32":
        return int.from_bytes(raw, byteorder=byteorder, signed=False)

    if fs.type == "q_fixed32":
        # stored as int32, interpreted as float = raw_int / 2^q
        vi = int.from_bytes(raw, byteorder=byteorder, signed=True)
        q = int(fs.q or 0)
        return vi / float(2**q)

    if fs.type == "float32":
        import struct

        fmt = "<f" if byteorder == "little" else ">f"
        return struct.unpack(fmt, raw)[0]

    raise TemplateError(f"Unhandled type={fs.type} for field={fs.name}")


def _encode_field(value: Any, fs: FieldSpec, endianness: str) -> bytes:
    byteorder = endianness

    if fs.type == "uint8":
        try:
            vi = int(0 if value is None else value)
        except Exception:
            vi = 0
        vi = max(0, min(255, vi))
        return bytes([vi])

    if fs.type == "int32":
        try:
            vi = int(0 if value is None else value)
        except Exception:
            vi = 0
        vi = max(-(2**31), min(2**31 - 1, vi))
        return int(vi).to_bytes(4, byteorder=byteorder, signed=True)

    if fs.type == "uint32":
        try:
            vi = int(0 if value is None else value)
        except Exception:
            vi = 0
        vi = max(0, min(2**32 - 1, vi))
        return int(vi).to_bytes(4, byteorder=byteorder, signed=False)

    if fs.type == "q_fixed32":
        try:
            vf = float(0.0 if value is None else value)
        except Exception:
            vf = 0.0
        # optional clamp to template range
        if fs.min is not None:
            vf = max(float(fs.min), vf)
        if fs.max is not None:
            vf = min(float(fs.max), vf)
        q = int(fs.q or 0)
        # Convert to int32 representation
        raw_i = int(vf * float(2**q))
        raw_i = max(-(2**31), min(2**31 - 1, raw_i))
        return int(raw_i).to_bytes(4, byteorder=byteorder, signed=True)

    if fs.type == "float32":
        import struct

        try:
            vf = float(0.0 if value is None else value)
        except Exception:
            vf = 0.0
        fmt = "<f" if byteorder == "little" else ">f"
        return struct.pack(fmt, vf)

    raise TemplateError(f"Unhandled type={fs.type} for field={fs.name}")
