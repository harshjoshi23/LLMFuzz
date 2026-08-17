"""Core data types used by the agent framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Constraint:
    """A single parameter constraint extracted from documentation."""

    name: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    valid_values: Optional[List[Any]] = None
    data_type: str = "int"
    unit: Optional[str] = None
    source: Optional[str] = None  # citation
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "min": self.min_value,
            "max": self.max_value,
            "valid_values": self.valid_values,
            "type": self.data_type,
            "unit": self.unit,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class Seed:
    """A fuzzing seed with metadata."""

    data: bytes
    protocol: str
    description: str
    category: str
    reasoning: str
    constraints_used: List[str] = field(default_factory=list)


@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Memory:
    """Agent memory for conversation context and extracted facts."""

    messages: List[Message] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    constraints_cache: Dict[str, Constraint] = field(default_factory=dict)

    def add(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))

    def add_fact(self, key: str, value: Any) -> None:
        self.facts[key] = value

    def get_context(self, n_messages: int = 10) -> List[Dict[str, str]]:
        recent = self.messages[-n_messages:]
        return [{"role": m.role, "content": m.content} for m in recent]
