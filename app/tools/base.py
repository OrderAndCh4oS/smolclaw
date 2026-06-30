from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry


ToolExposure = Literal["immediate", "deferred"]
ToolStatus = Literal["ok", "error", "denied"]
ToolEffect = Literal[
    "read",
    "workspace_write",
    "memory_write",
    "runtime_state_write",
    "command_read",
    "command_write",
    "image_management",
    "shell_session",
    "network",
    "delegation",
]

TRACE_RECORDER_STATE_KEY = "trace_recorder"
ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY = "active_tool_trace_event_id"
ACTIVE_TOOL_CALL_ID_STATE_KEY = "active_tool_call_id"


@dataclass
class ToolRuntimeContext:
    """Per-agent runtime state made available when binding tool instances.

    Stable shared-state keys:
    - ``trace_recorder``: current run trace recorder, when trace export is active.
    - ``active_tool_trace_event_id``: trace event id for the current ``tool.started`` event.
    - ``active_tool_call_id``: provider tool-call id for the current tool call, when available.
    """

    registry: Optional["ToolRegistry"] = None
    llm: Any = None
    hook_runner: Any = None
    session_manager: Any = None
    smol_rag: Any = None
    workspace: Any = None
    session_key: Optional[str] = None
    goal_store: Any = None
    child_agent_factory: Any = None
    loop_registrar: Any = None
    shared_state: dict[str, Any] = field(default_factory=dict)
    owned_resources: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class ToolCallPolicy:
    """Execution-time policy for a single tool invocation."""

    effects: frozenset[ToolEffect] = frozenset()
    requires_exploration: bool = False
    requires_approval: bool = False
    reversible: bool = False
    records_evidence: bool = True
    mutates_state: bool = False
    delegates: bool = False
    tags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ToolDescriptor:
    """Tool metadata independent of the legacy LLM schema format."""

    name: str
    description: str
    input_schema: dict
    output_schema: Optional[dict] = None
    examples: tuple[dict, ...] = ()
    exposure: ToolExposure = "immediate"
    default_policy: ToolCallPolicy = ToolCallPolicy()


@dataclass(frozen=True)
class ToolResult:
    """Typed tool result used by the runtime and policy layers."""

    status: ToolStatus
    content: str
    data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_legacy_text(self) -> str:
        return self.content


ToolOutcome = ToolResult | str


def normalize_tool_result(value: ToolOutcome | None) -> ToolResult:
    if isinstance(value, ToolResult):
        return value
    text = "" if value is None else str(value)
    lower_text = text.lower()
    if text.startswith("Denied:"):
        return ToolResult(status="denied", content=text)
    if "environment approval gate" in lower_text:
        return ToolResult(status="denied", content=text)
    if "error: approval required" in lower_text:
        return ToolResult(status="denied", content=text)
    if "denied by permission policy" in text:
        return ToolResult(status="denied", content=text)
    if "not permitted" in text:
        return ToolResult(status="denied", content=text)
    if "command is not allowlisted" in text:
        return ToolResult(status="denied", content=text)
    if text.startswith("Error:"):
        return ToolResult(status="error", content=text)
    return ToolResult(status="ok", content=text)


def render_tool_result(value: ToolOutcome | None) -> str:
    return normalize_tool_result(value).to_legacy_text()


def tool_policy_effects(policy: ToolCallPolicy) -> frozenset[str]:
    """Return explicit effects plus legacy tag-derived effects during migration."""
    effects = set(policy.effects)
    tags = set(policy.tags)
    if "filesystem_read" in tags:
        effects.add("read")
    if "filesystem_write" in tags:
        effects.add("workspace_write")
    if "shell_read" in tags:
        effects.add("command_read")
    if "shell_write" in tags:
        effects.add("command_write")
    if "command_execution" in tags and not {"command_read", "command_write"} & effects:
        effects.add("command_read")
    if policy.delegates:
        effects.add("delegation")
    if policy.mutates_state and "memory" in tags:
        effects.add("memory_write")
    if policy.mutates_state and not effects:
        effects.add("runtime_state_write")
    return frozenset(effects)


class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        ...

    @property
    def examples(self) -> List[dict]:
        """Optional usage examples for the LLM. Each dict has 'description' and 'arguments'."""
        return []

    @property
    def exposure(self) -> ToolExposure:
        """Controls whether the tool is visible immediately or only through discovery."""
        return "immediate"

    @property
    def deferred(self) -> bool:
        """Backward-compatible alias for tool discovery visibility."""
        return self.exposure == "deferred"

    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy()

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name=self.name,
            description=self.description,
            input_schema=self.parameters,
            examples=tuple(self.examples),
            exposure=self.exposure,
            default_policy=self.default_call_policy,
        )

    def bind(self, runtime_ctx: ToolRuntimeContext) -> "Tool":
        """Return a runtime-bound tool instance for a specific agent loop."""
        return self

    def get_call_policy(self, arguments: dict[str, Any] | None = None) -> ToolCallPolicy:
        return self.default_call_policy

    @abstractmethod
    async def execute(self, **kwargs) -> ToolOutcome:
        ...

    def to_schema(self) -> dict:
        descriptor = self.descriptor
        func = {
            "name": descriptor.name,
            "description": descriptor.description,
            "parameters": descriptor.input_schema,
        }
        if descriptor.examples:
            func["examples"] = list(descriptor.examples)
        return {"type": "function", "function": func}
