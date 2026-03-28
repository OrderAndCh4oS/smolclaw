from abc import ABC, abstractmethod
from typing import List


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
