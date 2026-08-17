"""Base class for all agents (LLM + memory)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from .types import Memory
from .llm_tracer import get_tracer, traced_call



class BaseAgent(ABC):
    def __init__(self, name: str, system_prompt: str):
        self.name = name
        self.system_prompt = system_prompt
        self.memory = Memory()
        self.llm_client = None

        # Optional run-scoped tracing for transparency/debugging.
        # If THESIS_FUZZER_LLM_TRACE is set to a file path, we will append
        # one JSON object per LLM call (JSONL).
        import os

        self._llm_trace_path = os.getenv("THESIS_FUZZER_LLM_TRACE")


    def _ensure_client(self):
        if self.llm_client is None:
            import os

            # Explicit toggle (default ON): thesis/evaluation mode assumes LLM usage.
            # Set THESIS_LLM_ENABLED=0 to force fully-offline runs.
            enabled = os.getenv("THESIS_LLM_ENABLED", "1").strip().lower() in {"1", "true", "yes", "y"}
            if not enabled:
                raise RuntimeError(
                    "LLM is disabled (THESIS_LLM_ENABLED=0). To enable agentic pipeline, set THESIS_LLM_ENABLED=1 "
                    "and provide GPT4IFX service-account env vars (GPT4IFX_CLIENT_ID/GPT4IFX_CLIENT_SECRET) "
                    "or GPT4IFX_API_KEY."
                )

            from src.utils.gpt4ifx_client import GPT4IFXClient
            from src.utils.model_selector import resolve_model_choice

            project_root = Path(__file__).resolve().parents[2]
            ca_bundle = str(project_root / "ca-bundle.crt")

            # Respect user env; if unset, default to repo-local CA bundle.
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)
            os.environ.setdefault("SSL_CERT_FILE", ca_bundle)

            # Resolve models based on what this tenant exposes.
            # Users can override via:
            #   GPT4IFX_MODEL_PRIMARY / GPT4IFX_MODEL_FALLBACK / GPT4IFX_MODEL_EMBEDDING
            #   GPT4IFX_MODEL_PREFERENCE / GPT4IFX_EMBEDDING_PREFERENCE
            tmp = GPT4IFXClient(ca_bundle_path=ca_bundle)
            available = tmp.client.models.list().data
            available_ids = [m.id for m in available]
            choice = resolve_model_choice(available_ids)

            self.llm_client = GPT4IFXClient(
                ca_bundle_path=ca_bundle,
                primary_model=choice.chat_primary,
                fallback_model=choice.chat_fallback,
            )
            # Expose selected models for token budgeting / dry-run reporting.
            self._model_choice = choice

    def think(self, user_input: str, temperature: float = 0.3, max_tokens: int = 2000) -> str:
        self._ensure_client()

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.memory.get_context())
        messages.append({"role": "user", "content": user_input})

        tracer = get_tracer()
        with traced_call() as tc:
            resp = self.llm_client.chat_completion(
                messages=messages, temperature=temperature, max_tokens=max_tokens
            )

        # Always log for thesis traceability.
        tracer.log_call(
            agent=self.name,
            purpose=f"think: {user_input[:80]}",
            prompt=messages,
            response=resp,
            duration_ms=tc.duration_ms,
        )

        # Back-compat: optional env-var JSONL trace file.
        if self._llm_trace_path:
            import json
            import os
            import time

            os.makedirs(os.path.dirname(self._llm_trace_path), exist_ok=True)
            record = {
                "ts": time.time(),
                "agent": self.name,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": messages,
                "response": resp,
            }
            with open(self._llm_trace_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")



        self.memory.add("user", user_input)
        self.memory.add("assistant", resp)
        return resp


    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError
