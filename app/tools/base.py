from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry


ToolExposure = Literal["immediate", "deferred"]
ToolStatus = Literal["ok", "error", "denied"]


@dataclass
class ToolRuntimeContext:
    """Per-agent runtime state made available when binding tool instances."""

    registry: Optional["ToolRegistry"] = None
    llm: Any = None
    hook_runner: Any = None
    session_manager: Any = None
    smol_rag: Any = None
    workspace: Any = None
    session_key: Optional[str] = None
    child_agent_factory: Any = None
    loop_registrar: Any = None
    shared_state: dict[str, Any] = field(default_factory=dict)
    owned_resources: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class ToolCallPolicy:
    """Execution-time policy for a single tool invocation."""

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
    if text.startswith("Denied:"):
        return ToolResult(status="denied", content=text)
    if text.startswith("Error:"):
        return ToolResult(status="error", content=text)
    return ToolResult(status="ok", content=text)


def render_tool_result(value: ToolOutcome | None) -> str:
    return normalize_tool_result(value).to_legacy_text()


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
