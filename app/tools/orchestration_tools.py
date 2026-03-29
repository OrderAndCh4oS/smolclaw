"""Tool wrappers for orchestration patterns."""

import json
from typing import Dict

from app.agent_config import AgentConfig
from app.agent_factory import ChildAgentFactory
from app.session import SessionManager
from app.tools.base import Tool, ToolCallPolicy, ToolRuntimeContext
from app.tools.registry import ToolRegistry


class SequentialPipelineTool(Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(delegates=True, tags=frozenset({"orchestration"}))

    @property
    def name(self) -> str:
        return "sequential_pipeline"

    @property
    def description(self) -> str:
        return (
            "Run agents in sequence: output of one becomes input to the next. "
            "Returns the final agent's response."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "agent_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of agent names to chain",
                },
                "input": {
                    "type": "string",
                    "description": "Input text for the first agent",
                },
            },
            "required": ["agent_names", "input"],
        }

    def __init__(
        self,
        configs: Dict[str, AgentConfig],
        master_registry: ToolRegistry,
        smol_rag,
        session_manager: SessionManager,
        child_agent_factory: ChildAgentFactory | None = None,
    ):
        self.configs = configs
        self.master_registry = master_registry
        self.smol_rag = smol_rag
        self.session_manager = session_manager
        self.child_agent_factory = child_agent_factory

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return SequentialPipelineTool(
            configs=self.configs,
            master_registry=self.master_registry,
            smol_rag=self.smol_rag,
            session_manager=self.session_manager,
            child_agent_factory=runtime_ctx.child_agent_factory or self.child_agent_factory,
        )

    async def execute(self, **kwargs) -> str:
        from app.orchestration import sequential_pipeline
        return await sequential_pipeline(
            agent_names=kwargs["agent_names"],
            initial_input=kwargs["input"],
            configs=self.configs,
            master_registry=self.master_registry,
            smol_rag=self.smol_rag,
            session_manager=self.session_manager,
            child_agent_factory=self.child_agent_factory,
        )


class FanoutPipelineTool(Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(delegates=True, tags=frozenset({"orchestration"}))

    @property
    def name(self) -> str:
        return "fanout_pipeline"

    @property
    def description(self) -> str:
        return (
            "Run multiple agents in parallel on the same input. "
            "Returns a JSON array of results (one per agent)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "agent_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of agent names to run in parallel",
                },
                "input": {
                    "type": "string",
                    "description": "Input text sent to all agents",
                },
            },
            "required": ["agent_names", "input"],
        }

    def __init__(
        self,
        configs: Dict[str, AgentConfig],
        master_registry: ToolRegistry,
        smol_rag,
        session_manager: SessionManager,
        child_agent_factory: ChildAgentFactory | None = None,
    ):
        self.configs = configs
        self.master_registry = master_registry
        self.smol_rag = smol_rag
        self.session_manager = session_manager
        self.child_agent_factory = child_agent_factory

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return FanoutPipelineTool(
            configs=self.configs,
            master_registry=self.master_registry,
            smol_rag=self.smol_rag,
            session_manager=self.session_manager,
            child_agent_factory=runtime_ctx.child_agent_factory or self.child_agent_factory,
        )

    async def execute(self, **kwargs) -> str:
        from app.orchestration import fanout_pipeline
        results = await fanout_pipeline(
            agent_names=kwargs["agent_names"],
            input_text=kwargs["input"],
            configs=self.configs,
            master_registry=self.master_registry,
            smol_rag=self.smol_rag,
            session_manager=self.session_manager,
            child_agent_factory=self.child_agent_factory,
        )
        return json.dumps(results, indent=2)


class RouteTool(Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(delegates=True, tags=frozenset({"orchestration"}))

    @property
    def name(self) -> str:
        return "route"

    @property
    def description(self) -> str:
        return (
            "Route input to the best-matching agent based on pattern matching. "
            "Routes map patterns/keywords to agent names."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "Input text to route",
                },
                "routes": {
                    "type": "object",
                    "description": "Mapping of pattern/keyword → agent_name",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["input", "routes"],
        }

    def __init__(
        self,
        configs: Dict[str, AgentConfig],
        master_registry: ToolRegistry,
        smol_rag,
        session_manager: SessionManager,
        child_agent_factory: ChildAgentFactory | None = None,
    ):
        self.configs = configs
        self.master_registry = master_registry
        self.smol_rag = smol_rag
        self.session_manager = session_manager
        self.child_agent_factory = child_agent_factory

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        return RouteTool(
            configs=self.configs,
            master_registry=self.master_registry,
            smol_rag=self.smol_rag,
            session_manager=self.session_manager,
            child_agent_factory=runtime_ctx.child_agent_factory or self.child_agent_factory,
        )

    async def execute(self, **kwargs) -> str:
        from app.orchestration import route
        return await route(
            input_text=kwargs["input"],
            routes=kwargs["routes"],
            configs=self.configs,
            master_registry=self.master_registry,
            smol_rag=self.smol_rag,
            session_manager=self.session_manager,
            child_agent_factory=self.child_agent_factory,
        )
