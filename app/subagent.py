import asyncio
from typing import Dict

from app.agent_config import AgentConfig
from app.agent_factory import build_agent_loop
from app.session import SessionManager
from app.tools.registry import ToolRegistry


class SubagentManager:
    def __init__(
        self,
        configs: Dict[str, AgentConfig],
        master_registry: ToolRegistry,
        smol_rag,
        session_manager: SessionManager,
        max_concurrent: int = 5,
    ):
        self.configs = configs
        self.master_registry = master_registry
        self.smol_rag = smol_rag
        self.session_manager = session_manager
        self.max_concurrent = max_concurrent
        self._tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, str] = {}
        self._counter = 0

    async def spawn(self, agent_name: str, goal: str) -> str:
        if agent_name not in self.configs:
            return f"Error: unknown agent '{agent_name}'"
        active = len([t for t in self._tasks.values() if not t.done()])
        if active >= self.max_concurrent:
            return f"Error: max concurrent subagents ({self.max_concurrent}) reached"

        self._counter += 1
        task_id = f"sub-{self._counter}"
        config = self.configs[agent_name]
        loop = build_agent_loop(
            config, self.master_registry, self.smol_rag,
            self.session_manager, session_key_prefix=task_id,
        )
        task = asyncio.create_task(self._run(task_id, loop, goal))
        self._tasks[task_id] = task
        return task_id

    async def _run(self, task_id: str, loop, goal: str):
        try:
            result = await loop.process(goal)
            self._results[task_id] = result
        except Exception as e:
            self._results[task_id] = f"Error: agent failed — {e}"

    def get_result(self, task_id: str) -> str:
        if task_id not in self._tasks:
            return f"Error: unknown task '{task_id}'"
        if not self._tasks[task_id].done():
            return "pending"
        return self._results.get(task_id, "Error: no result")

    async def await_result(self, task_id: str, timeout: float = 300) -> str:
        if task_id not in self._tasks:
            return f"Error: unknown task '{task_id}'"
        try:
            await asyncio.wait_for(self._tasks[task_id], timeout=timeout)
        except asyncio.TimeoutError:
            self._tasks[task_id].cancel()
            return f"Error: agent timed out after {timeout}s"
        return self._results.get(task_id, "Error: no result")
