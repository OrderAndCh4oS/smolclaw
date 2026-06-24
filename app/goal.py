import time
from dataclasses import dataclass, field


VALID_GOAL_STATUSES = {"active", "complete", "blocked"}


@dataclass
class GoalState:
    objective: str
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    note: str = ""
    turn_count: int = 0

    def __post_init__(self):
        if self.status not in VALID_GOAL_STATUSES:
            supported = ", ".join(sorted(VALID_GOAL_STATUSES))
            raise ValueError(f"Invalid goal status '{self.status}'. Expected one of: {supported}.")

    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "note": self.note,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GoalState":
        return cls(
            objective=str(data.get("objective") or ""),
            status=str(data.get("status") or "active"),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            note=str(data.get("note") or ""),
            turn_count=int(data.get("turn_count") or 0),
        )

    def render_for_prompt(self) -> str:
        lines = [
            "Current session goal:",
            f"- Objective: {self.objective}",
            f"- Status: {self.status}",
            f"- Goal turns: {self.turn_count}",
        ]
        if self.note:
            lines.append(f"- Note: {self.note}")
        lines.append(
            "Continue working toward this goal unless the user redirects. "
            "Use goal_update when it is complete or blocked."
        )
        return "\n".join(lines)
