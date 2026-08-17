"""Strict run artifact schema + lightweight validation.

Design goals:
- No heavy dependencies (no pydantic/jsonschema).
- Enforce a minimal, stable structure for *all* agent/pipeline outputs.
- Provide clear error paths for reports and CI.

This is intentionally conservative: it validates types, required keys, and enum values.
It does not attempt deep domain validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


SCHEMA_VERSION = "1.0"


RUN_STATUS = {"running", "completed", "failed", "canceled"}
STAGE_STATUS = {"pending", "running", "completed", "failed", "skipped"}
VALIDATION_STATUS = {"not_run", "passed", "failed"}


_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def now_utc_iso_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ValidationErrorItem:
    path: str
    message: str


def _is_iso_z(s: Any) -> bool:
    return isinstance(s, str) and bool(_ISO_Z_RE.match(s))


def _is_sha256(s: Any) -> bool:
    return isinstance(s, str) and bool(_SHA256_RE.match(s))


def _err(errors: List[ValidationErrorItem], path: str, msg: str) -> None:
    errors.append(ValidationErrorItem(path=path, message=msg))


def validate_run_json(obj: Any) -> Tuple[bool, List[ValidationErrorItem]]:
    errors: List[ValidationErrorItem] = []

    if not isinstance(obj, dict):
        _err(errors, "$", "run.json is not an object")
        return False, errors

    # required top-level
    for k in ["schemaVersion", "runId", "createdAt", "status", "paths", "pipeline", "validation"]:
        if k not in obj:
            _err(errors, f"$.{k}", "missing")

    if errors:
        return False, errors

    if obj.get("schemaVersion") != SCHEMA_VERSION:
        _err(errors, "$.schemaVersion", f"must be {SCHEMA_VERSION!r}")

    if not isinstance(obj.get("runId"), str) or not obj["runId"].strip():
        _err(errors, "$.runId", "must be a non-empty string")

    if not _is_iso_z(obj.get("createdAt")):
        _err(errors, "$.createdAt", "must be ISO-8601 UTC '...Z' (no ms)")

    if obj.get("status") not in RUN_STATUS:
        _err(errors, "$.status", f"must be one of {sorted(RUN_STATUS)}")

    # paths
    paths = obj.get("paths")
    if not isinstance(paths, dict):
        _err(errors, "$.paths", "must be an object")
    else:
        for k in ["runJson", "workDir", "logsDir", "artifactsDir"]:
            if k not in paths:
                _err(errors, f"$.paths.{k}", "missing")
            elif not isinstance(paths[k], str) or not paths[k].strip():
                _err(errors, f"$.paths.{k}", "must be a non-empty string")

    # pipeline + stages
    pipeline = obj.get("pipeline")
    if not isinstance(pipeline, dict):
        _err(errors, "$.pipeline", "must be an object")
    else:
        if not isinstance(pipeline.get("name"), str) or not pipeline["name"].strip():
            _err(errors, "$.pipeline.name", "must be a non-empty string")
        stages = pipeline.get("stages")
        if not isinstance(stages, list):
            _err(errors, "$.pipeline.stages", "must be an array")
        else:
            seen_ids: set[str] = set()
            for i, st in enumerate(stages):
                pfx = f"$.pipeline.stages[{i}]"
                if not isinstance(st, dict):
                    _err(errors, pfx, "stage must be an object")
                    continue

                sid = st.get("id")
                if not isinstance(sid, str) or not sid.strip():
                    _err(errors, f"{pfx}.id", "missing/empty")
                else:
                    if sid in seen_ids:
                        _err(errors, f"{pfx}.id", "duplicate")
                    seen_ids.add(sid)

                if not isinstance(st.get("name"), str) or not st["name"].strip():
                    _err(errors, f"{pfx}.name", "missing/empty")

                if st.get("status") not in STAGE_STATUS:
                    _err(errors, f"{pfx}.status", f"must be one of {sorted(STAGE_STATUS)}")

                for tkey in ["startedAt", "endedAt"]:
                    if tkey in st and st[tkey] is not None and not _is_iso_z(st[tkey]):
                        _err(errors, f"{pfx}.{tkey}", "must be ISO-8601 UTC '...Z' (no ms)")

                v = st.get("validation")
                if v is not None:
                    _validate_validation_obj(errors, f"{pfx}.validation", v)

                # agent outputs are optional
                agents = st.get("agents")
                if agents is not None:
                    if not isinstance(agents, list):
                        _err(errors, f"{pfx}.agents", "must be an array")
                    else:
                        for j, a in enumerate(agents):
                            apfx = f"{pfx}.agents[{j}]"
                            if not isinstance(a, dict):
                                _err(errors, apfx, "agent must be an object")
                                continue
                            if not isinstance(a.get("agentId"), str) or not a["agentId"].strip():
                                _err(errors, f"{apfx}.agentId", "missing/empty")
                            if not isinstance(a.get("type"), str) or not a["type"].strip():
                                _err(errors, f"{apfx}.type", "missing/empty")
                            if "validation" in a:
                                _validate_validation_obj(errors, f"{apfx}.validation", a["validation"])

    _validate_validation_obj(errors, "$.validation", obj.get("validation"))

    return (len(errors) == 0), errors


def _validate_validation_obj(errors: List[ValidationErrorItem], path: str, v: Any) -> None:
    if not isinstance(v, dict):
        _err(errors, path, "must be an object")
        return

    if v.get("status") not in VALIDATION_STATUS:
        _err(errors, f"{path}.status", f"must be one of {sorted(VALIDATION_STATUS)}")

    if "checkedAt" in v and v["checkedAt"] is not None and not _is_iso_z(v["checkedAt"]):
        _err(errors, f"{path}.checkedAt", "must be ISO-8601 UTC '...Z' (no ms)")

    if "errors" in v and not isinstance(v["errors"], list):
        _err(errors, f"{path}.errors", "must be an array")


def new_run_skeleton(*, run_id: str, pipeline_name: str, work_dir: str) -> Dict[str, Any]:
    """Create a new run.json skeleton.

    Paths must be relative to repo root; caller decides layout.
    """

    now = now_utc_iso_z()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "createdAt": now,
        "status": "running",
        "paths": {
            "runJson": f"{work_dir}/run.json",
            "workDir": work_dir,
            "logsDir": f"{work_dir}/logs",
            "artifactsDir": f"{work_dir}/artifacts",
        },
        "pipeline": {"name": pipeline_name, "stages": []},
        "validation": {"status": "not_run", "validator": "run_schema.py@1.0", "checkedAt": None, "errors": []},
    }
