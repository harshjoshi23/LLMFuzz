"""Centralized model selection for GPT4IFX.

Goals:
- One place to decide which model IDs to use
- Prefer non-retiring, generally-available models
- Allow user overrides via environment variables
- Avoid hardcoding model IDs across agents/CLI/RAG

Model IDs must match GPT4IFX OpenAI API `/models` response.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional


# Models the user said are available in their tenant (from /models output).
# Keep these OpenAI-style IDs.
# Single-model policy (thesis reproducibility):
# We intentionally prefer ONE chat model that is known to work in the tenant.
# This avoids brittle fallbacks to models that may be disabled/retired.
DEFAULT_CHAT_PREFERENCE: list[str] = [
    # GPT4IFX-native models (direct gateway, no Bedrock VPN hop — reliable)
    "gpt-5.2",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    # Llama via GPT4IFX proxy (also direct)
    "llama3.3-70b",
    "mixtral",
    # Bedrock-routed models (VPN endpoint — times out under load, last resort)
    "claudesonnet4.5",
]

DEFAULT_EMBEDDING_PREFERENCE: list[str] = [
    "sfr-embedding-mistral",
    "text-embedding-3-small",
    "text-embedding-ada-002",
    "multilingual-e5-large-instruct",
]


@dataclass(frozen=True)
class ModelChoice:
    chat_primary: str
    chat_fallback: str
    embedding: str


def _parse_csv(val: str) -> list[str]:
    return [x.strip() for x in val.split(",") if x.strip()]


def choose_from_available(
    available: Iterable[str],
    *,
    preference: list[str],
    override: Optional[str] = None,
    allow_retiring: bool = True,
) -> str:
    """Pick the first preferred model that exists in available.

    override:
      - if set, must exist in available, otherwise ValueError.

    allow_retiring:
      - if false, will skip GPT-4o/o3-mini/o4-mini and any -chat variants.
        (used when we want conservative defaults)
    """

    available_set = set(available)

    if override:
        if override not in available_set:
            raise ValueError(f"Requested model {override!r} is not available. Available includes: {sorted(list(available_set))[:30]}...")
        return override

    retiring_blocklist = {"gpt-4o", "gpt-4o-mini", "o3-mini"}

    for m in preference:
        if m not in available_set:
            continue
        if not allow_retiring and m in retiring_blocklist:
            continue
        return m

    # Fallback: pick any deterministic model id
    if available_set:
        return sorted(available_set)[0]

    raise ValueError("No models available to choose from")


def resolve_model_choice(available_models: Iterable[str]) -> ModelChoice:
    """Resolve final model choices using env overrides.

    Env overrides:
      - GPT4IFX_MODEL_PRIMARY
      - GPT4IFX_MODEL_FALLBACK
      - GPT4IFX_MODEL_EMBEDDING
      - GPT4IFX_MODEL_PREFERENCE (comma-separated list)
      - GPT4IFX_EMBEDDING_PREFERENCE (comma-separated list)
    """

    pref = DEFAULT_CHAT_PREFERENCE
    epref = DEFAULT_EMBEDDING_PREFERENCE

    pref_env = os.getenv("GPT4IFX_MODEL_PREFERENCE")
    if pref_env:
        pref = _parse_csv(pref_env)

    epref_env = os.getenv("GPT4IFX_EMBEDDING_PREFERENCE")
    if epref_env:
        epref = _parse_csv(epref_env)

    primary_override = os.getenv("GPT4IFX_MODEL_PRIMARY")
    fallback_override = os.getenv("GPT4IFX_MODEL_FALLBACK")
    embedding_override = os.getenv("GPT4IFX_MODEL_EMBEDDING")

    primary = choose_from_available(
        available_models,
        preference=pref,
        override=primary_override,
        allow_retiring=False,
    )

    # Single-model policy: keep fallback identical to primary unless explicitly overridden.
    fallback = primary

    embedding = choose_from_available(
        available_models,
        preference=epref,
        override=embedding_override,
        allow_retiring=True,
    )

    return ModelChoice(chat_primary=primary, chat_fallback=fallback, embedding=embedding)
