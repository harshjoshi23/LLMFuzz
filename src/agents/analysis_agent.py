"""Agent 3: Crash analysis and feedback generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseAgent


class AnalysisAgent(BaseAgent):
    SYSTEM_PROMPT = """You are a firmware crash analysis specialist.
Analyze crash artifacts and suggest what to test next.
Return strict JSON.
"""

    def __init__(self):
        super().__init__(name="AnalysisAgent", system_prompt=self.SYSTEM_PROMPT)
        self.crashes_analyzed: List[Dict[str, Any]] = []

    def analyze_crashes(self, crashes_dir: str, protocol: str = "unknown") -> Dict[str, Any]:
        from src.utils.llm_json import parse_json_object

        p = Path(crashes_dir)
        if not p.exists():
            return {"next_suggestions": [], "note": f"crashes_dir not found: {crashes_dir}"}

        # Summarize a few crash files
        samples: List[Dict[str, Any]] = []
        for f in sorted(p.glob("*") )[:10]:
            if f.is_file():
                try:
                    b = f.read_bytes()
                    samples.append({"file": f.name, "size": len(b), "head_hex": b[:16].hex()})
                except Exception:
                    continue

        prompt = (
            f"Crash samples for protocol={protocol}:\n{json.dumps(samples, indent=2)}\n\n"
            "Return JSON object with keys: crash_type, trigger, hypothesis, next_suggestions (array of strings), unexplored_areas (array)."
        )

        resp = self.think(prompt)
        try:
            obj = parse_json_object(resp)
        except Exception:
            obj = {"error": "Failed to parse analysis", "raw": resp}

        return {"next_suggestions": obj.get("next_suggestions", []), "analysis": obj}

    def run(self, crashes_dir: str, protocol: str = "unknown") -> Dict[str, Any]:
        return self.analyze_crashes(crashes_dir=crashes_dir, protocol=protocol)
