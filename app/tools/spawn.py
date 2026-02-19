from app.subagent import SubagentManager
from app.tools.base import Tool


class SpawnTool(Tool):
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

    def __init__(self, manager: SubagentManager):
        self.manager = manager

    async def execute(self, **kwargs) -> str:
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

    def __init__(self, manager: SubagentManager):
        self.manager = manager

    async def execute(self, **kwargs) -> str:
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

    def __init__(self, manager: SubagentManager):
        self.manager = manager

    async def execute(self, **kwargs) -> str:
        return await self.manager.await_result(kwargs["task_id"])
