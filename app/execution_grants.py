"""Scoped execution grants produced by exact-call approvals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


NETWORK_EFFECT = "network"
IMAGE_MANAGEMENT_EFFECT = "image_management"
SHELL_SESSION_EFFECT = "shell_session"


@dataclass(frozen=True)
class ExecutionGrant:
    """Authority granted to one approved tool invocation."""

    tool_name: str
    arguments_hash: str
    approval_id: str
    effects: frozenset[str]
    run_id: str | None = None

    def allows(self, effect: str) -> bool:
        return effect in self.effects

    @classmethod
    def from_approval(cls, approval, *, effects: Iterable[str]) -> "ExecutionGrant":
        return cls(
            tool_name=approval.tool_name,
            arguments_hash=approval.arguments_hash,
            approval_id=approval.id,
            effects=frozenset(str(effect) for effect in effects),
            run_id=approval.run_id,
        )
