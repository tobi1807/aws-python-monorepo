"""Base class for domain events published on the shared EventBridge bus.

Rules for every event model:
- Additive changes only (new optional fields). Removing or renaming a field is
  a breaking change: use expand-then-contract and let Pact tell you who reads it.
- Consumers are tolerant readers: unknown fields are ignored.
- Each module holds one producer's events. Keep __init__.py empty so importing
  one module never drags in the others (narrow dependency graph = fewer
  "affected" apps when a contract changes).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    SOURCE: ClassVar[str]
    DETAIL_TYPE: ClassVar[str]

    def to_detail(self) -> str:
        """JSON string for the EventBridge ``Detail`` field."""
        return self.model_dump_json()
