from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry


@dataclass
class ToolRuntimeContext:
    """Per-agent runtime state made available when binding tool instances."""

    registry: Optional["ToolRegistry"] = None
    llm: Any = None
    hook_runner: Any = None
    session_manager: Any = None
    smol_rag: Any = None
    session_key: Optional[str] = None
    child_agent_factory: Any = None
    loop_registrar: Any = None
    shared_state: dict[str, Any] = field(default_factory=dict)
    owned_resources: list[Any] = field(default_factory=list)


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
    def deferred(self) -> bool:
        """If True, this tool's schema is excluded from initial definitions and discoverable via tool_search."""
        return False

    def bind(self, runtime_ctx: ToolRuntimeContext) -> "Tool":
        """Return a runtime-bound tool instance for a specific agent loop."""
        return self

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        ...

    def to_schema(self) -> dict:
        func = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
        if self.examples:
            func["examples"] = self.examples
        return {"type": "function", "function": func}
