from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


_ENV = "THESIS_BLACKBOARD_PATH"


def get_blackboard_path() -> Optional[Path]:
    p = os.environ.get(_ENV)
    if not p:
        return None
    try:
        return Path(p)
    except Exception:
        return None


@dataclass
class BlackboardEvent:
    ts: str
    component: str
    event_type: str
    fields: Dict[str, Any]


def _utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def bb_event(component: str, event_type: str, **fields: Any) -> None:
    """Append a single JSONL event to the per-run blackboard if enabled.

    This is intentionally best-effort and never raises.
    """

    path = get_blackboard_path()
    if path is None:
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ev = BlackboardEvent(ts=_utc_ts(), component=component, event_type=event_type, fields=fields)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ev.ts, "component": ev.component, "event_type": ev.event_type, **ev.fields}, sort_keys=True) + "\n")
    except Exception:
        return
