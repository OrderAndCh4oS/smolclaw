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
                "acceptance_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional acceptance criteria that define when the goal is done.",
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

    async def execute(
        self,
        objective: str,
        acceptance_criteria: list[str] | None = None,
        **kwargs,
    ) -> ToolOutcome:
        if self.goal_store is None or not self.session_key:
            return "Error: goal_start is not bound to a session."
        try:
            try:
                goal = self.goal_store.start(
                    self.session_key,
                    objective,
                    acceptance_criteria=acceptance_criteria,
                )
            except TypeError:
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
        criteria = getattr(goal, "acceptance_criteria", None) or []
        criteria_block = ""
        if criteria:
            criteria_block = "\nAcceptance criteria:\n" + "\n".join(
                f"- [{item.status}] {item.description}" for item in criteria
            )
        verification = getattr(goal, "verification", None) or []
        verification_block = ""
        if verification:
            verification_block = "\nVerification:\n" + "\n".join(
                f"- [{item.status}] {item.summary or item.command}" for item in verification
            )
        return (
            f"Goal: {goal.objective}\n"
            f"Status: {goal.status}\n"
            f"Turns: {goal.turn_count}"
            f"{note}"
            f"{criteria_block}"
            f"{verification_block}"
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
        return "Update the session goal plan, acceptance criteria, status, or note."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "complete", "blocked"],
                    "description": "Optional new status for the active goal.",
                },
                "plan": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional replacement plan as concise step descriptions.",
                },
                "current_step": {
                    "type": "string",
                    "description": "Plan step id or exact description to mark as current.",
                },
                "acceptance_updates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "description": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "satisfied", "not_applicable"],
                            },
                            "evidence": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ],
                            },
                        },
                        "additionalProperties": False,
                    },
                    "description": "Narrow updates to existing acceptance criteria.",
                },
                "note": {
                    "type": "string",
                    "description": "Brief reason or summary for the status change.",
                },
                "no_verification_reason": {
                    "type": "string",
                    "description": (
                        "Explicit reason verification is not possible or not applicable. "
                        "Use only when completing a goal without verification evidence."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def bind(self, runtime_ctx: ToolRuntimeContext) -> "GoalUpdateTool":
        return GoalUpdateTool(
            goal_store=getattr(runtime_ctx, "goal_store", None),
            session_key=runtime_ctx.session_key,
        )

    async def execute(
        self,
        status: str | None = None,
        note: str = "",
        plan: list[str] | None = None,
        current_step: str | None = None,
        acceptance_updates: list[dict] | None = None,
        no_verification_reason: str = "",
        **kwargs,
    ) -> ToolOutcome:
        if self.goal_store is None or not self.session_key:
            return "Error: goal_update is not bound to a session."
        try:
            try:
                goal = self.goal_store.update(
                    self.session_key,
                    status=status,
                    note=note,
                    plan=plan,
                    current_step=current_step,
                    acceptance_updates=acceptance_updates,
                    no_verification_reason=no_verification_reason,
                )
            except TypeError:
                if status is None:
                    return "Error: legacy goal store requires status."
                goal = self.goal_store.update(self.session_key, status=status, note=note)
        except ValueError as exc:
            return f"Error: {exc}"
        if status is None:
            return f"Goal updated: {goal.objective}"
        suffix = f" Note: {goal.note}" if goal.note else ""
        return f"Goal marked {goal.status}.{suffix}"


class GoalRecordEvidenceTool(Tool):
    def __init__(self, goal_store=None, session_key: str | None = None):
        self.goal_store = goal_store
        self.session_key = session_key

    @property
    def name(self) -> str:
        return "goal_record_evidence"

    @property
    def description(self) -> str:
        return (
            "Record structured evidence for the active goal: files inspected, "
            "commands run, verification, or checkpoints."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["read", "search", "status", "diff", "command", "test", "checkpoint"],
                },
                "summary": {"type": "string"},
                "path": {"type": "string"},
                "command": {"type": "string"},
                "status": {"type": "string"},
                "tool_call_id": {"type": "string"},
                "trace_event_id": {"type": "string"},
            },
            "required": ["kind", "summary"],
            "additionalProperties": False,
        }

    def bind(self, runtime_ctx: ToolRuntimeContext) -> "GoalRecordEvidenceTool":
        return GoalRecordEvidenceTool(
            goal_store=getattr(runtime_ctx, "goal_store", None),
            session_key=runtime_ctx.session_key,
        )

    async def execute(
        self,
        kind: str,
        summary: str,
        path: str | None = None,
        command: str | None = None,
        status: str | None = None,
        tool_call_id: str | None = None,
        trace_event_id: str | None = None,
        **kwargs,
    ) -> ToolOutcome:
        if self.goal_store is None or not self.session_key:
            return "Error: goal_record_evidence is not bound to a session."
        record_evidence = getattr(self.goal_store, "record_evidence", None)
        if not callable(record_evidence):
            return "Error: active goal store does not support structured evidence."
        try:
            goal = record_evidence(
                self.session_key,
                kind=kind,
                summary=summary,
                path=path,
                command=command,
                status=status,
                tool_call_id=tool_call_id,
                trace_event_id=trace_event_id,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Recorded {kind} evidence for goal: {goal.objective}"
