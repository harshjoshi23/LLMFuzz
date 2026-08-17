"""Extension/Plugin registry (foundation).

This is intentionally lightweight: it documents extension points without adding heavy dependencies.

Extension points:
- target adapters (new harness types)
- doc processors (custom chunking/parsing)
- report formats

Usage: register factories in code or via future entrypoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Type


@dataclass
class Registry:
    target_adapters: Dict[str, Callable[..., Any]]
    doc_processors: Dict[str, Callable[..., Any]]
    report_formats: Dict[str, Callable[..., Any]]


_global = Registry(target_adapters={}, doc_processors={}, report_formats={})


def register_target_adapter(name: str, factory: Callable[..., Any]) -> None:
    _global.target_adapters[name] = factory


def get_target_adapter(name: str) -> Callable[..., Any]:
    if name not in _global.target_adapters:
        raise KeyError(f"No target adapter registered: {name}")
    return _global.target_adapters[name]


def register_doc_processor(name: str, factory: Callable[..., Any]) -> None:
    _global.doc_processors[name] = factory


def register_report_format(name: str, factory: Callable[..., Any]) -> None:
    _global.report_formats[name] = factory
