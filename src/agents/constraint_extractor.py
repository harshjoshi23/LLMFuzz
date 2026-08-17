"""Agent 1: Constraint extraction using RAG + LLM.

This agent is used by the orchestrator/pipeline to extract parameter constraints
from project documentation via RAG.

Key requirements (thesis-ready):
- Cap output size to avoid truncation.
- Cap context size to avoid huge generations.
- Robustly salvage truncated JSON.
- Provide a per-section (per retrieved chunk) fallback path.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .base import BaseAgent
from .types import Constraint


class ConstraintExtractorAgent(BaseAgent):
    SYSTEM_PROMPT = """You are a hardware constraint extraction specialist.
Your job is to extract precise parameter constraints from technical documentation.

When given datasheet text, extract ALL constraints you can find.
ALWAYS output valid JSON.
"""

    def __init__(self):
        super().__init__(name="ConstraintExtractor", system_prompt=self.SYSTEM_PROMPT)
        self.rag_pipeline = None

    def _ensure_rag(self, *, index_dir: str | None = None, datasheet_dir: str | None = None):
        if self.rag_pipeline is None:
            from pathlib import Path

            from src.rag_pipeline.rag_pipeline import RAGPipeline

            vectorstore_dir = index_dir or "data/vectorstore"
            datasheets = datasheet_dir or "data/datasheets"

            self.rag_pipeline = RAGPipeline(
                datasheet_dir=str(datasheets),
                vectorstore_dir=str(vectorstore_dir),
                allow_no_auth=False,
            )
            self.rag_pipeline.load_index()

            if index_dir is not None:
                p = Path(index_dir)
                if not p.exists():
                    raise FileNotFoundError(f"RAG index_dir not found: {p}")

    def query_documentation(
        self,
        query: str,
        top_k: int = 5,
        *,
        index_dir: str | None = None,
        datasheet_dir: str | None = None,
    ) -> Tuple[str, List[str]]:
        self._ensure_rag(index_dir=index_dir, datasheet_dir=datasheet_dir)

        results = self.rag_pipeline.retrieve(
            query=query,
            top_k=top_k,
            similarity_threshold=0.3,
            show_results=False,
        )
        if not results:
            return "", []

        ctx = "\n\n---\n\n".join([r["text"] for r in results])
        cites = [r["citation"] for r in results]
        return ctx, cites

    def extract_constraints_per_section(
        self,
        topic: str,
        *,
        index_dir: str | None = None,
        datasheet_dir: str | None = None,
        top_k: int = 5,
    ) -> List[Constraint]:
        """Fallback extraction: run one extraction per retrieved chunk.

        - Limits each call to smaller context to avoid truncation.
        - Deduplicates by constraint name, keeping highest-confidence entry.
        """

        from src.utils.llm_json import LLMOutputParseError, parse_json_array, validate_constraint_items

        self._ensure_client()
        self._ensure_rag(index_dir=index_dir, datasheet_dir=datasheet_dir)

        results = self.rag_pipeline.retrieve(query=topic, top_k=top_k, similarity_threshold=0.3, show_results=False)
        if not results:
            return []

        best: dict[str, Constraint] = {}

        for r in results:
            chunk_text = r.get("text", "")
            if not chunk_text:
                continue

            prompt = (
                "Extract parameter constraints from this datasheet excerpt.\n"
                "Return at most 10 constraints from THIS excerpt only.\n"
                "Return ONLY valid JSON array (no prose, no markdown, no code fences).\n"
                "Output MUST start with '[' and end with ']'.\n\n"
                f"TEXT:\n{chunk_text}\n"
            )

            try:
                resp = self.think(prompt, temperature=0.1, max_tokens=3000)
                items = [x for x in parse_json_array(resp) if isinstance(x, dict)]
                ok, msg = validate_constraint_items(items)
                if not ok:
                    raise LLMOutputParseError(msg)
            except Exception:
                # skip this chunk
                continue

            for item in items[:10]:
                c = Constraint(
                    name=item.get("name", "UNKNOWN"),
                    min_value=item.get("min"),
                    max_value=item.get("max"),
                    valid_values=item.get("valid_values"),
                    data_type=item.get("type", "int"),
                    unit=item.get("unit"),
                    source=r.get("citation"),
                    confidence=item.get("confidence", 0.5),
                )
                prev = best.get(c.name)
                if prev is None or (c.confidence or 0.0) > (prev.confidence or 0.0):
                    best[c.name] = c

        return list(best.values())

    def extract_constraints(self, topic: str, *, index_dir: str | None = None, datasheet_dir: str | None = None) -> List[Constraint]:
        """Single-shot extraction with bounded output, bounded context and robust repair.

        If single-shot extraction yields 0 constraints, automatically falls back to per-section extraction.
        """

        import json

        from src.utils.llm_json import LLMOutputParseError, parse_json_array, strip_code_fences, validate_constraint_items
        from src.utils.token_counter import count_tokens

        self._ensure_client()

        context, citations = self.query_documentation(topic, index_dir=index_dir, datasheet_dir=datasheet_dir)
        if not context:
            return []

        model_name = getattr(getattr(self, "_model_choice", None), "chat_primary", "cl100k_base")

        # 1.2 Bound input context
        ctx_tokens = count_tokens(context, model=model_name)
        max_ctx_tokens = 6000
        if ctx_tokens.tokens > max_ctx_tokens:
            ratio = max_ctx_tokens / max(ctx_tokens.tokens, 1)
            new_len = max(1000, int(len(context) * ratio))
            context = context[:new_len]
            new_tc = count_tokens(context, model=model_name)
            print(f"[{self.name}] context truncated from {ctx_tokens.tokens} to {new_tc.tokens} tokens")
            ctx_tokens = new_tc

        # 1.1 Bound output
        prompt = f"""Extract parameter constraints from this datasheet text.

Return at most 30 constraints. Prioritize constraints with explicit numeric min/max in the text.
If more than 30 exist, return the 30 most safety-critical.

Formatting rules:
- Return ONLY valid JSON (no prose, no markdown, no code fences)
- Output MUST start with '[' and end with ']'
- name <= 60 chars
- unit <= 16 chars
- valid_values array length <= 12

(TOKEN_BUDGET)
- model={model_name}
- context_tokens={ctx_tokens.tokens} (encoding={ctx_tokens.encoding}, approx={ctx_tokens.approx})

TEXT FROM DATASHEET:
{context}

Schema per item: {{name, min, max, valid_values, type, unit, confidence}}

Return ONLY the JSON array."""

        response = self.think(prompt, temperature=0.1, max_tokens=6000)

        last_err: Optional[Exception] = None

        for _attempt in range(3):
            try:
                payload = None
                try:
                    payload = json.loads(strip_code_fences(response))
                except Exception:
                    payload = None

                if isinstance(payload, list):
                    items = [x for x in payload if isinstance(x, dict)]
                else:
                    items = [x for x in parse_json_array(response) if isinstance(x, dict)]

                ok, msg = validate_constraint_items(items)
                if not ok:
                    raise LLMOutputParseError(msg)

                out: List[Constraint] = []
                for item in items[:30]:
                    out.append(
                        Constraint(
                            name=item.get("name", "UNKNOWN"),
                            min_value=item.get("min"),
                            max_value=item.get("max"),
                            valid_values=item.get("valid_values"),
                            data_type=item.get("type", "int"),
                            unit=item.get("unit"),
                            source=citations[0] if citations else None,
                            confidence=item.get("confidence", 0.5),
                        )
                    )

                if out:
                    print(f"[{self.name}] Single-shot extraction returned {len(out)} constraints")
                    return out
                raise LLMOutputParseError("0 constraints")

            except Exception as e:
                last_err = e

                # 1.1 Repair previous output (do NOT re-extract)
                response = self.think(
                    "Your previous output was not valid JSON. Repair it. "
                    "Output MUST start with '[' and end with ']'. No code fences, no commentary. "
                    "Schema per item: {name, min, max, valid_values, type, unit, confidence}. "
                    "Truncate to at most 30 items if needed.\n\n"
                    f"PREVIOUS_OUTPUT:\n{response}",
                    temperature=0.0,
                    max_tokens=6000,
                )

        print(f"[{self.name}] Failed to parse constraints after retries: {last_err}")

        # 1.4 Fallback: per-section extraction
        print(f"[{self.name}] Falling back to per-section extraction")
        per = self.extract_constraints_per_section(topic, index_dir=index_dir, datasheet_dir=datasheet_dir)
        print(f"[{self.name}] Per-section extraction returned {len(per)} constraints")
        return per

    def run(self, topics=None):
        raise NotImplementedError("Use extract_constraints(topic=...)")
