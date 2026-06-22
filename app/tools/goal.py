from app.tools.base import Tool, ToolOutcome, ToolRuntimeContext


class GoalStartTool(Tool):
    def __init__(self, goal_store=None, session_key: str | None = None):
        self.goal_store = goal_store
        self.session_key = session_key

    @property
    def name(self) -> str:
        return "goal_start"

    @property
    def description(self) -> str:
        return (
            "Start or replace the active session goal. Use this when the user asks "
            "to make a plan, task, or objective into the current goal."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "Concrete objective to persist as the active session goal.",
                },
            },
            "required": ["objective"],
            "additionalProperties": False,
        }

    def bind(self, runtime_ctx: ToolRuntimeContext) -> "GoalStartTool":
        return GoalStartTool(
            goal_store=getattr(runtime_ctx, "goal_store", None),
            session_key=runtime_ctx.session_key,
        )

    async def execute(self, objective: str, **kwargs) -> ToolOutcome:
        if self.goal_store is None or not self.session_key:
            return "Error: goal_start is not bound to a session."
        try:
            goal = self.goal_store.start(self.session_key, objective)
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Goal set: {goal.objective}"


class GoalStatusTool(Tool):
    def __init__(self, goal_store=None, session_key: str | None = None):
        self.goal_store = goal_store
        self.session_key = session_key

    @property
    def name(self) -> str:
        return "goal_status"

    @property
    def description(self) -> str:
        return "Show the active session goal, including status, note, and completed goal turns."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def bind(self, runtime_ctx: ToolRuntimeContext) -> "GoalStatusTool":
        return GoalStatusTool(
            goal_store=getattr(runtime_ctx, "goal_store", None),
            session_key=runtime_ctx.session_key,
        )

    async def execute(self, **kwargs) -> ToolOutcome:
        if self.goal_store is None or not self.session_key:
            return "Error: goal_status is not bound to a session."
        goal = self.goal_store.load(self.session_key)
        if goal is None:
            return "No goal is set for this session."
        note = f"\nNote: {goal.note}" if goal.note else ""
        return (
            f"Goal: {goal.objective}\n"
            f"Status: {goal.status}\n"
            f"Turns: {goal.turn_count}"
            f"{note}"
        )


class GoalUpdateTool(Tool):
    def __init__(self, goal_store=None, session_key: str | None = None):
        self.goal_store = goal_store
        self.session_key = session_key

    @property
    def name(self) -> str:
        return "goal_update"

    @property
    def description(self) -> str:
        return "Mark the session goal as complete or blocked, with an optional note."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["complete", "blocked"],
                    "description": "The terminal status for the active goal.",
                },
                "note": {
                    "type": "string",
                    "description": "Brief reason or summary for the status change.",
                },
            },
            "required": ["status"],
            "additionalProperties": False,
        }

    def bind(self, runtime_ctx: ToolRuntimeContext) -> "GoalUpdateTool":
        return GoalUpdateTool(
            goal_store=getattr(runtime_ctx, "goal_store", None),
            session_key=runtime_ctx.session_key,
        )

    async def execute(self, status: str, note: str = "", **kwargs) -> ToolOutcome:
        if self.goal_store is None or not self.session_key:
            return "Error: goal_update is not bound to a session."
        try:
            goal = self.goal_store.update(self.session_key, status=status, note=note)
        except ValueError as exc:
            return f"Error: {exc}"
        suffix = f" Note: {goal.note}" if goal.note else ""
        return f"Goal marked {goal.status}.{suffix}"
