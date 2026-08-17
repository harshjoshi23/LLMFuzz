"""Log all LLM interactions for thesis reproducibility.

Writes JSONL (one JSON object per line) to `logs/llm_trace.jsonl` by default.

This is separate from any older env-var based tracing; BaseAgent will use this
tracer unconditionally so thesis runs always have an audit trail.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class LLMTracer:
    def __init__(self, log_file: str = "logs/llm_trace.jsonl"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log_call(
        self,
        *,
        agent: str,
        purpose: str,
        prompt: Any,
        response: Any,
        rag_context: Optional[str] = None,
        duration_ms: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "purpose": purpose,
            "prompt": prompt,
            "response": response,
            "rag_context": rag_context,
            "duration_ms": duration_ms,
        }
        if extra:
            entry.update(extra)

        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


_tracer: Optional[LLMTracer] = None


def get_tracer() -> LLMTracer:
    global _tracer
    if _tracer is None:
        _tracer = LLMTracer()
    return _tracer


class traced_call:
    """Context manager to time an LLM call."""

    def __init__(self):
        self._start = 0.0
        self.duration_ms: Optional[float] = None

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.duration_ms = (time.time() - self._start) * 1000.0
        return False
