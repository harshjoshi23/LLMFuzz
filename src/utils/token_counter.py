"""Token counting utilities (thesis reproducibility).

We use tiktoken for approximate token counts.
If a model name isn't known to tiktoken, we fall back to cl100k_base and
record that choice.

This is used for:
- constraint extraction prompt sizing
- seed generator prompt sizing
- dry-run reporting
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TokenCountResult:
    tokens: int
    encoding: str
    model: str
    approx: bool


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    return str(x)


def _approx_token_count(text: str) -> int:
    """Deterministic fallback when tiktoken is unavailable.

    A 4-character heuristic is conservative enough for dry-run reporting and
    keeps tests usable before the full requirements file is installed.
    """

    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def count_tokens(text: Any, *, model: str) -> TokenCountResult:
    """Return approximate token count for `text`.

    If `model` is not recognized by tiktoken, falls back to cl100k_base.
    """

    s = _safe_str(text)
    approx = False

    try:
        import tiktoken
    except ModuleNotFoundError:
        return TokenCountResult(
            tokens=_approx_token_count(s),
            encoding="cl100k_base",
            model=model,
            approx=True,
        )

    try:
        enc = tiktoken.encoding_for_model(model)
        encoding_name = getattr(enc, "name", "<unknown>")
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
        encoding_name = "cl100k_base"
        approx = True

    return TokenCountResult(tokens=len(enc.encode(s)), encoding=encoding_name, model=model, approx=approx)


def count_tokens_messages(messages: list[dict[str, Any]], *, model: str) -> TokenCountResult:
    """Very rough token estimate for chat messages.

    We approximate by concatenating role/content with separators.
    This is good enough for budgeting and dry-run reporting.
    """

    parts: list[str] = []
    for m in messages:
        role = _safe_str(m.get("role"))
        content = _safe_str(m.get("content"))
        parts.append(f"{role}: {content}")
    joined = "\n".join(parts)
    return count_tokens(joined, model=model)
