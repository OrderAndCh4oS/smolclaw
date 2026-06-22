import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional


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


class GoalStore:
    """Stores one goal sidecar per chat session."""

    def __init__(self, sessions_dir: str):
        self.sessions_dir = sessions_dir
        os.makedirs(sessions_dir, exist_ok=True)

    def _file_path(self, session_key: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_key}.goal.json")

    def load(self, session_key: str) -> Optional[GoalState]:
        path = self._file_path(session_key)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return GoalState.from_dict(json.load(f))

    def save(self, session_key: str, goal: GoalState) -> GoalState:
        goal.updated_at = time.time()
        path = self._file_path(session_key)
        with open(path, "w") as f:
            json.dump(goal.to_dict(), f, indent=2)
        return goal

    def start(self, session_key: str, objective: str) -> GoalState:
        objective = objective.strip()
        if not objective:
            raise ValueError("Goal objective cannot be empty.")
        return self.save(session_key, GoalState(objective=objective))

    def update(self, session_key: str, status: str, note: str = "") -> GoalState:
        if status not in VALID_GOAL_STATUSES:
            supported = ", ".join(sorted(VALID_GOAL_STATUSES))
            raise ValueError(f"Invalid goal status '{status}'. Expected one of: {supported}.")
        goal = self.load(session_key)
        if goal is None:
            raise ValueError("No goal is set for this session.")
        goal.status = status
        goal.note = note.strip()
        return self.save(session_key, goal)

    def clear(self, session_key: str) -> bool:
        path = self._file_path(session_key)
        if not os.path.exists(path):
            return False
        os.remove(path)
        return True

    def increment_turn_count(self, session_key: str) -> Optional[GoalState]:
        goal = self.load(session_key)
        if goal is None or goal.status != "active":
            return goal
        goal.turn_count += 1
        return self.save(session_key, goal)
