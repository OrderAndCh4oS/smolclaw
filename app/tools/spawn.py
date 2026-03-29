from typing import Dict, Optional

from app.agent_config import AgentConfig
from app.subagent import SubagentManager
from app.tools.base import Tool, ToolCallPolicy, ToolRuntimeContext

_RUNTIME_MANAGER_KEY = "subagent_manager"


def _bind_manager(
    runtime_ctx: ToolRuntimeContext,
    configs: Dict[str, AgentConfig] | None,
    manager: Optional[SubagentManager],
    max_concurrent: int,
) -> Optional[SubagentManager]:
    if manager is not None:
        return manager
    if not configs or not runtime_ctx.child_agent_factory:
        return None
    bound_manager = runtime_ctx.shared_state.get(_RUNTIME_MANAGER_KEY)
    if bound_manager is None:
        bound_manager = SubagentManager(
            configs=configs,
            child_agent_factory=runtime_ctx.child_agent_factory,
            max_concurrent=max_concurrent,
        )
        runtime_ctx.shared_state[_RUNTIME_MANAGER_KEY] = bound_manager
        runtime_ctx.owned_resources.append(bound_manager)
    return bound_manager


class SpawnTool(Tool):
    @property
    def default_call_policy(self) -> ToolCallPolicy:
        return ToolCallPolicy(delegates=True, tags=frozenset({"subagent"}))

    @property
    def name(self) -> str:
        return "spawn_agent"

    @property
    def description(self) -> str:
        return "Spawn a subagent to work on a task in the background."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Name of agent config to spawn",
                },
                "goal": {
                    "type": "string",
                    "description": "Task/goal for the subagent",
                },
            },
            "required": ["agent_name", "goal"],
        }

    def __init__(
        self,
        manager: Optional[SubagentManager] = None,
        configs: Dict[str, AgentConfig] | None = None,
        max_concurrent: int = 5,
    ):
        self.manager = manager
        self.configs = configs
        self.max_concurrent = max_concurrent

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        manager = _bind_manager(runtime_ctx, self.configs, self.manager, self.max_concurrent)
        return SpawnTool(
            manager=manager,
            configs=self.configs,
            max_concurrent=self.max_concurrent,
        )

    async def execute(self, **kwargs) -> str:
        if self.manager is None:
            return "Error: subagent manager is not available"
        return await self.manager.spawn(kwargs["agent_name"], kwargs["goal"])


class GetResultTool(Tool):
    @property
    def name(self) -> str:
        return "get_result"

    @property
    def description(self) -> str:
        return "Check the result of a spawned subagent task (non-blocking, returns 'pending' if not done)."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID from spawn_agent",
                },
            },
            "required": ["task_id"],
        }

    def __init__(
        self,
        manager: Optional[SubagentManager] = None,
        configs: Dict[str, AgentConfig] | None = None,
        max_concurrent: int = 5,
    ):
        self.manager = manager
        self.configs = configs
        self.max_concurrent = max_concurrent

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        manager = _bind_manager(runtime_ctx, self.configs, self.manager, self.max_concurrent)
        return GetResultTool(
            manager=manager,
            configs=self.configs,
            max_concurrent=self.max_concurrent,
        )

    async def execute(self, **kwargs) -> str:
        if self.manager is None:
            return "Error: subagent manager is not available"
        return self.manager.get_result(kwargs["task_id"])


class AwaitResultTool(Tool):
    @property
    def name(self) -> str:
        return "await_result"

    @property
    def description(self) -> str:
        return "Wait for a spawned subagent to finish and return its result. Blocks until complete."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID from spawn_agent",
                },
            },
            "required": ["task_id"],
        }

    def __init__(
        self,
        manager: Optional[SubagentManager] = None,
        configs: Dict[str, AgentConfig] | None = None,
        max_concurrent: int = 5,
    ):
        self.manager = manager
        self.configs = configs
        self.max_concurrent = max_concurrent

    def bind(self, runtime_ctx: ToolRuntimeContext) -> Tool:
        manager = _bind_manager(runtime_ctx, self.configs, self.manager, self.max_concurrent)
        return AwaitResultTool(
            manager=manager,
            configs=self.configs,
            max_concurrent=self.max_concurrent,
        )

    async def execute(self, **kwargs) -> str:
        if self.manager is None:
            return "Error: subagent manager is not available"
        return await self.manager.await_result(kwargs["task_id"])
