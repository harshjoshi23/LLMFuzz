"""JSON parsing helpers for LLM outputs.

Goal: eliminate flaky parsing by providing:
- strict JSON extraction from common LLM wrappers (```json ... ```)
- schema-ish validation for expected shapes
- retry/repair prompts in agents (kept local to agents.py for now)

This module is dependency-free.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


class LLMOutputParseError(ValueError):
    pass


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = _CODE_FENCE_RE.sub("", t).strip()
    return t


def extract_first_json_array(text: str) -> Optional[str]:
    """Best-effort extraction of the first JSON array in a string.

    Strategy: scan for the first '[' and then track bracket depth until the
    matching closing ']'.

    If the output is truncated and we never see the matching ']', return the
    prefix starting at '[' so salvage logic can still recover partial items.
    """

    s = text
    start = s.find("[")
    if start < 0:
        return None

    depth = 0
    in_str = False
    escape = False

    for i in range(start, len(s)):
        ch = s[i]

        if in_str:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]

    # Truncated: return prefix for salvage attempts.
    return s[start:]


def extract_first_json_object(text: str) -> Optional[str]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else None


def parse_json_array(text: str) -> List[Any]:
    cleaned = strip_code_fences(text)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, list):
            return obj
    except json.JSONDecodeError:
        pass

    arr = extract_first_json_array(text)
    if arr is None:
        raise LLMOutputParseError("No JSON array found in LLM output")

    def _try_load(s: str) -> Optional[list[Any]]:
        try:
            o = json.loads(s)
            return o if isinstance(o, list) else None
        except json.JSONDecodeError:
            return None

    # 1) Normal parse
    obj = _try_load(arr)
    if obj is not None:
        return obj

    # 2) Repair trailing commas
    repaired = re.sub(r",\s*([\]}])", r"\1", arr)
    obj = _try_load(repaired)
    if obj is not None:
        return obj

    # 3) Salvage truncated output: close array after last complete object
    last_obj_end = repaired.rfind("}")
    if last_obj_end > 0:
        candidate = repaired[: last_obj_end + 1].rstrip()
        if "[" in candidate:
            candidate = candidate + "]"
            obj = _try_load(candidate)
            if obj is not None:
                return obj

    raise LLMOutputParseError("Invalid JSON array in LLM output")


def parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = strip_code_fences(text)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    s = extract_first_json_object(text)
    if s is None:
        raise LLMOutputParseError("No JSON object found in LLM output")

    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        raise LLMOutputParseError(f"Invalid JSON object in LLM output: {e}") from e

    if not isinstance(obj, dict):
        raise LLMOutputParseError("Extracted JSON is not an object")
    return obj


def validate_constraint_items(items: List[Any]) -> Tuple[bool, str]:
    """Light validation: each item should be a dict with a name."""
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            return False, f"constraint[{i}] is not an object"
        if not it.get("name"):
            return False, f"constraint[{i}].name missing"
    return True, "ok"


def validate_seed_suggestions(items: List[Any]) -> Tuple[bool, str]:
    """Light validation for SeedGeneratorAgent suggestions."""
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            return False, f"suggestion[{i}] is not an object"
        if not it.get("parameter"):
            return False, f"suggestion[{i}].parameter missing"
        if "value" not in it:
            return False, f"suggestion[{i}].value missing"
        if not it.get("category"):
            return False, f"suggestion[{i}].category missing"
        if not it.get("reasoning"):
            return False, f"suggestion[{i}].reasoning missing"
    return True, "ok"


def validate_analysis_output(obj: Any) -> Tuple[bool, str]:
    """Light validation for AnalysisAgent output.

    Expected shape (minimal):
      {"next_suggestions": ["..."], "analysis": {...}} OR {"analysis": {...}, ...}

    We enforce that next_suggestions is a list of strings if present.
    """
    if not isinstance(obj, dict):
        return False, "analysis output is not an object"

    ns = obj.get("next_suggestions")
    if ns is not None:
        if not isinstance(ns, list):
            return False, "next_suggestions is not a list"
        for i, s in enumerate(ns):
            if not isinstance(s, str) or not s.strip():
                return False, f"next_suggestions[{i}] is not a non-empty string"

    # allow 'analysis' to be missing in error cases
    if "analysis" in obj and not isinstance(obj["analysis"], dict):
        return False, "analysis is not an object"

    return True, "ok"
