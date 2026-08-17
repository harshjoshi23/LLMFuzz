"""
__init__.py for utils package

IMPORTANT:
- Keep this module lightweight.
- Do NOT import heavy/optional network dependencies at import time.

Rationale:
- Report parsing / offline tooling should work even if GPT4IFX client deps (e.g. httpx)
  are not installed in the current Python environment.
"""

from .csv_constraints import load_constraints_from_csv, merge_constraints

__all__ = [
    "load_constraints_from_csv",
    "merge_constraints",
]

# Optional GPT4IFX client exports
try:
    from .gpt4ifx_client import GPT4IFXClient, create_client

    __all__ += ["GPT4IFXClient", "create_client"]
except Exception:
    # Allow running without GPT4IFX deps (e.g., report-only environment)
    pass

