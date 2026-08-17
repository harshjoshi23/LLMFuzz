"""Extract parameter constraints using LLM + documentation.

This module maps a parsed parameter struct (from `header_parser`) into constraints
needed by `TemplateInputModel` YAML.

Design goals:
- Prefer correctness and traceability over cleverness.
- If the LLM fails (network/auth/schema), fall back to deterministic heuristics.
- Keep the output schema simple and YAML-ready.

The LLM interface used in this repo is `chat_completion(messages=...)` as implemented
by `src.utils.gpt4ifx_client.GPT4IFXClient` and `src.utils.mock_llm_client.MockLLMClient`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .header_parser import StructDef, StructField

logger = logging.getLogger(__name__)


class ConstraintExtractor:
    """Extract valid ranges and encoding info from docs using an LLM."""

    def __init__(self, llm_client: Any, docs_dir: Optional[Path] = None):
        """Initialize constraint extractor.

        Args:
            llm_client: LLM client instance with `chat_completion(messages=...) -> str`.
            docs_dir: Optional directory containing docs/CSVs to use as context.
        """

        self.llm = llm_client
        self.docs_dir = Path(docs_dir) if docs_dir else None

    def extract_constraints(self, struct_def: StructDef, function_name: str) -> Dict[str, Dict[str, Any]]:
        """Extract constraints for struct fields.

        Args:
            struct_def: Parsed struct definition.
            function_name: Associated init function (context for docs/prompt).

        Returns:
            Dict mapping field name -> constraint dict:
            {
              "field": {"type": "int32_t", "encoding": "Q23", "min": -1.0, "max": 1.0, "description": "..."}
            }
        """

        doc_context = self._retrieve_docs(function_name, struct_def.name) if self.docs_dir else ""
        prompt = self._build_prompt(struct_def, function_name, doc_context)

        try:
            resp = self.llm.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a careful embedded firmware analyst."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
            constraints = self._parse_response(resp)
            return self._validate_constraints(constraints, struct_def)
        except Exception as e:
            logger.error("LLM extraction failed: %s", e)
            logger.info("Falling back to heuristic defaults")
            return self._heuristic_defaults(struct_def)

    def _build_prompt(self, struct_def: StructDef, function_name: str, doc_context: str) -> str:
        """Build the LLM prompt for constraint extraction."""

        struct_text = self._format_struct(struct_def)
        ctx = doc_context if doc_context else "No documentation found. Use field names/types/comments to infer constraints."

        return f"""You are analyzing embedded firmware code for parameter constraint extraction.

Function: {function_name}
Struct: {struct_def.name}

Struct definition:
```c
{struct_text}
```

Documentation context:
{ctx}

Task: For each struct field, infer:
- encoding: one of [Q23, Q15, float, int, uint]
- min/max: range in the *decoded/semantic* domain
- description: short human description

Heuristics if unclear:
- name/comment contains q23 -> Q23, range [-1.0, 1.0]
- name/comment contains q15 -> Q15, range [-1.0, 1.0]
- fields containing scale/shift/gain -> int, range [0, 15]
- float -> [-10.0, 10.0]
- uint -> [0, 65535]
- int -> [-32768, 32767]

Output JSON only (no markdown), mapping field name to object:
{{
  "field": {{"type": "int32_t", "encoding": "Q23", "min": -1.0, "max": 1.0, "description": "..."}},
  ...
}}
"""

    def _format_struct(self, struct_def: StructDef) -> str:
        """Format struct for prompt."""

        lines = ["typedef struct {"]
        for f in struct_def.fields:
            c = f"  // {f.comment}" if f.comment else ""
            lines.append(f"    {f.c_type} {f.name};{c}")
        lines.append(f"}} {struct_def.name};")
        return "\n".join(lines)

    def _retrieve_docs(self, func_name: str, struct_name: str) -> str:
        """Retrieve relevant documentation snippets (best-effort)."""

        if not self.docs_dir or not self.docs_dir.exists():
            return ""

        parts: list[str] = []
        for csv_file in self.docs_dir.glob("**/*.csv"):
            try:
                content = csv_file.read_text(errors="ignore")
            except Exception:
                continue

            if func_name.lower() in content.lower() or struct_name.lower() in content.lower():
                parts.append(f"From {csv_file.name}:\n{content[:800]}...")

        return "\n\n".join(parts)

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Extract JSON from LLM response."""

        text = response.strip()
        if "```json" in text:
            start = text.index("```json") + len("```json")
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + len("```")
            end = text.index("```", start)
            text = text[start:end].strip()

        return json.loads(text)

    def _validate_constraints(self, constraints: Dict[str, Any], struct_def: StructDef) -> Dict[str, Dict[str, Any]]:
        """Validate and fill missing entries."""

        out: Dict[str, Dict[str, Any]] = {}
        for field in struct_def.fields:
            if field.name in constraints and isinstance(constraints[field.name], dict):
                out[field.name] = constraints[field.name]
            else:
                logger.warning("Missing constraints for %s; using heuristic", field.name)
                out[field.name] = self._heuristic_for_field(field)

        # Ensure required keys
        for k, v in out.items():
            v.setdefault("type", "")
            v.setdefault("encoding", "int")
            v.setdefault("min", -32768)
            v.setdefault("max", 32767)
            v.setdefault("description", f"Parameter {k}")

        return out

    def _heuristic_defaults(self, struct_def: StructDef) -> Dict[str, Dict[str, Any]]:
        """Fallback: generate constraints using heuristics only."""

        return {f.name: self._heuristic_for_field(f) for f in struct_def.fields}

    def _heuristic_for_field(self, field: StructField) -> Dict[str, Any]:
        """Heuristic constraint inference for a single field."""

        name_lower = field.name.lower()
        comment_lower = (field.comment or "").lower()

        if "q23" in name_lower or "q23" in comment_lower:
            return {
                "type": field.c_type,
                "encoding": "Q23",
                "min": -1.0,
                "max": 1.0,
                "description": f"Fixed-point Q23 parameter {field.name}",
            }

        if "q15" in name_lower or "q15" in comment_lower:
            return {
                "type": field.c_type,
                "encoding": "Q15",
                "min": -1.0,
                "max": 1.0,
                "description": f"Fixed-point Q15 parameter {field.name}",
            }

        if "float" in field.c_type:
            return {
                "type": field.c_type,
                "encoding": "float",
                "min": -10.0,
                "max": 10.0,
                "description": f"Floating-point parameter {field.name}",
            }

        if "scale" in name_lower or "shift" in name_lower or "gain" in name_lower:
            return {
                "type": field.c_type,
                "encoding": "int",
                "min": 0,
                "max": 15,
                "description": f"Scaling parameter {field.name}",
            }

        if "uint" in field.c_type:
            return {
                "type": field.c_type,
                "encoding": "uint",
                "min": 0,
                "max": 65535,
                "description": f"Unsigned integer {field.name}",
            }

        return {
            "type": field.c_type,
            "encoding": "int",
            "min": -32768,
            "max": 32767,
            "description": f"Integer parameter {field.name}",
        }
