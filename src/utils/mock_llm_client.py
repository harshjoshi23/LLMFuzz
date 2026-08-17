"""Mock LLM client for offline thesis demos and unit tests.

Implements the minimal interface used by BaseAgent:
- chat_completion(messages, temperature, max_tokens) -> str
- embed_text(text, model) -> List[float]

Outputs are deterministic and schema-correct for the agents in this repo.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List


class MockLLMClient:
    def chat_completion(self, messages: List[Dict[str, str]], temperature: float = 0.0, max_tokens: int = 2000, **kwargs) -> str:
        # Use last user message to decide what schema to return
        user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user = m.get("content", "")
                break

        # Constraint extraction output
        if "Return a JSON array of constraints" in user or "Extract all parameter constraints" in user:
            return json.dumps(
                [
                    {"name": "I2C_ADDRESS", "min": 32, "max": 39, "valid_values": None, "type": "hex", "unit": None, "confidence": 0.9},
                    {"name": "I2C_REG", "min": 0, "max": 255, "valid_values": None, "type": "int", "unit": None, "confidence": 0.8},
                ]
            )

        # Seed suggestion output
        if "Return ONLY a JSON array" in user and "parameter" in user and "reasoning" in user:
            return json.dumps(
                [
                    {"parameter": "I2C_ADDRESS", "value": 32, "category": "boundary", "reasoning": "min address"},
                    {"parameter": "I2C_ADDRESS", "value": 39, "category": "boundary", "reasoning": "max address"},
                    {"parameter": "I2C_REG", "value": 0, "category": "boundary", "reasoning": "min register"},
                    {"parameter": "I2C_REG", "value": 255, "category": "boundary", "reasoning": "max register"},
                ]
            )

        # Analysis output
        if "Return JSON object" in user and "next_suggestions" in user:
            return json.dumps(
                {
                    "crash_type": "none",
                    "trigger": "n/a",
                    "hypothesis": "n/a",
                    "next_suggestions": ["try boundary values", "try invalid command"],
                    "unexplored_areas": ["state machine"],
                }
            )

        # Peripheral emulation output
        if "output_schema" in user and "data_hex" in user:
            return json.dumps({"ack": True, "data_hex": "0000", "notes": "mock"})

        return json.dumps({"ok": True})

    def embed_text(self, text: str, model: str = "text-embedding-3-small") -> List[float]:
        # Deterministic 1536-dim embedding from sha256
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vals = [b / 255.0 for b in h]
        # Repeat to reach 1536
        out = (vals * (1536 // len(vals) + 1))[:1536]
        return out
