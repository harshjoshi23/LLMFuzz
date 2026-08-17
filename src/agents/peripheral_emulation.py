"""Peripheral emulation agent.

Note: This is a lightweight wrapper around the existing behavior from the monolithic implementation.
It generates JSON-structured responses for reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import BaseAgent


@dataclass
class PeripheralResponse:
    data: bytes
    ack: bool
    notes: str = ""
    source_citations: Optional[List[str]] = None


class PeripheralEmulationAgent(BaseAgent):
    SYSTEM_PROMPT = """You emulate peripheral device responses for firmware fuzzing.
Return strict JSON only."""

    def __init__(self):
        super().__init__(name="PeripheralEmulationAgent", system_prompt=self.SYSTEM_PROMPT)

    def emulate_read(self, protocol: str, address: int, register: int, length: int, mode: str = "realistic") -> PeripheralResponse:
        from src.utils.llm_json import parse_json_object

        prompt: Dict[str, Any] = {
            "protocol": protocol,
            "address": address,
            "register": register,
            "length": length,
            "mode": mode,
            "output_schema": {"ack": "bool", "data_hex": "string", "notes": "string"},
        }

        resp = self.think(
            "Generate a realistic peripheral READ response as JSON matching output_schema. "
            f"INPUT:\n{json.dumps(prompt, indent=2)}"
        )

        obj = parse_json_object(resp)
        data_hex = str(obj.get("data_hex", ""))
        try:
            data = bytes.fromhex(data_hex)[:length]
        except Exception:
            data = b"\x00" * length

        return PeripheralResponse(
            data=data,
            ack=bool(obj.get("ack", True)),
            notes=str(obj.get("notes", "")),
            source_citations=None,
        )

    def run(self, *args: Any, **kwargs: Any):
        raise NotImplementedError("Use emulate_read(...)")
