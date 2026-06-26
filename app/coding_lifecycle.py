"""Core coding lifecycle domain contracts.

These types describe the unified coding lifecycle without binding it to Jira,
GitHub, or the current work-loop implementation. Existing work-loop classes can
adapt to these contracts incrementally while preserving their public API.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


LifecyclePhase = Literal[
    "discovered",
    "recommended",
    "implementing",
    "verifying",
    "reviewing",
    "publishing",
    "open-pr",
    "responding-to-review",
    "done",
    "blocked",
    "failed",
]

LifecycleSourceKind = Literal["discovery", "source_control"]
PublicationKind = Literal["commit", "push", "pull_request", "source_status", "comment"]


@dataclass(frozen=True)
class LifecycleSourceRef:
    kind: LifecycleSourceKind
    provider: str
    key: str
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublicationRef:
    kind: PublicationKind
    provider: str
    identifier: str
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewFeedbackRef:
    provider: str
    pr_number: int | None
    comment_id: str = ""
    body: str = ""
    source: str = "comment"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CodingLifecycleWork:
    source_ref: LifecycleSourceRef
    title: str
    phase: LifecyclePhase = "discovered"
    description: str = ""
    branch_name: str = ""
    workspace_path: str = ""
    publication_refs: list[PublicationRef] = field(default_factory=list)
    review_feedback: list[ReviewFeedbackRef] = field(default_factory=list)
    handled_feedback_ids: list[str] = field(default_factory=list)
    blocker: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CodingPassResult:
    success: bool
    summary: str
    verification: list[Any] = field(default_factory=list)
    manual_steps: str = ""
    blocker: str = ""
    attempts: int = 0
    capped: bool = False


@dataclass(frozen=True)
class PublicationResult:
    ok: bool
    refs: tuple[PublicationRef, ...] = ()
    message: str = ""


class WorkDiscoveryAdapter(Protocol):
    def auth_ok(self) -> bool:
        ...

    def discover(self, config: Any, *, limit: int = 50) -> list[CodingLifecycleWork]:
        ...

    def load(self, source_ref: LifecycleSourceRef) -> CodingLifecycleWork:
        ...

    def update_status(self, source_ref: LifecycleSourceRef, phase: LifecyclePhase):
        ...

    def comment(self, source_ref: LifecycleSourceRef, body: str):
        ...


class SourceControlReviewAdapter(Protocol):
    def auth_ok(self) -> bool:
        ...

    def discover_followups(self, config: Any) -> list[CodingLifecycleWork]:
        ...

    def respond(self, feedback: ReviewFeedbackRef, body: str) -> PublicationResult:
        ...


class PublicationAdapter(Protocol):
    def commit_push_open_pr(self, work: CodingLifecycleWork, result: CodingPassResult) -> PublicationResult:
        ...

    def update_source_status(self, source_ref: LifecycleSourceRef, phase: LifecyclePhase) -> PublicationResult:
        ...

    def comment(self, target: PublicationRef | LifecycleSourceRef, body: str) -> PublicationResult:
        ...


class CodingPassExecutor(Protocol):
    def execute(
        self,
        work: CodingLifecycleWork,
        *,
        review_feedback: str = "",
        profile: Any = None,
    ) -> CodingPassResult:
        ...
