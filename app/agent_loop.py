import json
from typing import Awaitable, Callable, Optional

from app.context_builder import ContextBuilder
from app.definitions import MAX_ITERATIONS, MEMORY_WINDOW
from app.hooks import HookRunner, ON_SESSION_START, ON_BEFORE_TURN, ON_AFTER_TURN, ON_COMPACTION_FLUSH, ON_SESSION_END
from app.logger import logger
from app.session import Session, SessionManager
from app.tools.registry import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        llm,
        tool_registry: ToolRegistry,
        context_builder: ContextBuilder,
        session: Session,
        session_manager: SessionManager,
        max_iterations: int = MAX_ITERATIONS,
        memory_window: int = MEMORY_WINDOW,
        smol_rag=None,
        hook_runner: Optional[HookRunner] = None,
    ):
        self.llm = llm
        self.tool_registry = tool_registry
        self.context_builder = context_builder
        self.session = session
        self.session_manager = session_manager
        self.max_iterations = max_iterations
        self.memory_window = memory_window
        self.smol_rag = smol_rag
        self.hook_runner = hook_runner or HookRunner()
        self._stop_after_current = False
        self._session_started = False

    async def process(
        self,
        user_content: str,
        on_output: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        if not self._session_started:
            self._session_started = True
            await self.hook_runner.fire(ON_SESSION_START, {
                "session_key": self.session.key,
            })

        self.session.add_message({"role": "user", "content": user_content})

        await self._maybe_consolidate()

        history = self.session.get_history(self.memory_window)
        # Remove the last user message from history since build_messages adds it
        if history and history[-1]["role"] == "user" and history[-1]["content"] == user_content:
            history = history[:-1]

        messages = await self.context_builder.build_messages_async(
            history=history,
            user_content=user_content,
        )

        tools = self.tool_registry.get_definitions() or None

        for iteration in range(self.max_iterations):
            if self._stop_after_current:
                msg = "Stopped: time limit reached."
                self.session.add_message({"role": "assistant", "content": msg})
                self.session_manager.save(self.session)
                return msg

            await self.hook_runner.fire(ON_BEFORE_TURN, {
                "iteration": iteration,
                "session_key": self.session.key,
                "user_content": user_content,
            })

            result = await self.llm.get_tool_completion(
                messages=messages,
                tools=tools,
            )

            if not result["has_tool_calls"]:
                content = result["content"] or ""
                if on_output and content:
                    await on_output(content)
                self.session.add_message({"role": "assistant", "content": content})
                self.session_manager.save(self.session)

                await self.hook_runner.fire(ON_AFTER_TURN, {
                    "iteration": iteration,
                    "session_key": self.session.key,
                    "response": content,
                    "had_tool_calls": False,
                })
                return content

            # Process tool calls
            assistant_msg = {"role": "assistant", "content": result["content"]}
            if result["tool_calls"]:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in result["tool_calls"]
                ]
            messages.append(assistant_msg)

            for tool_call in result["tool_calls"]:
                name = tool_call["name"]
                arguments = tool_call["arguments"]

                tool_result = await self.tool_registry.execute(name, arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result,
                })

            await self.hook_runner.fire(ON_AFTER_TURN, {
                "iteration": iteration,
                "session_key": self.session.key,
                "tool_calls": [tc["name"] for tc in result["tool_calls"]],
                "had_tool_calls": True,
            })

        # Exceeded max iterations
        msg = "Stopped: reached max iterations without a final response."
        self.session.add_message({"role": "assistant", "content": msg})
        self.session_manager.save(self.session)
        return msg

    def request_stop(self):
        """Signal the loop to stop after the current iteration completes."""
        self._stop_after_current = True

    async def close(self):
        """Fire session end hooks. Call this when the session is ending."""
        await self.hook_runner.fire(ON_SESSION_END, {
            "session_key": self.session.key,
            "session": self.session,
        })

    async def _maybe_consolidate(self):
        if not self.smol_rag:
            return
        total = len(self.session.messages)
        unconsolidated = total - self.session.last_consolidated
        if unconsolidated <= self.memory_window:
            return

        start = self.session.last_consolidated
        end = total
        to_consolidate = self.session.messages[start:end]

        text_parts = []
        for msg in to_consolidate:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                text_parts.append(f"{role}: {content}")

        if text_parts:
            text = "\n".join(text_parts)
            await self.smol_rag.ingest_text(text, source_id=f"session-{self.session.key}")

            await self.hook_runner.fire(ON_COMPACTION_FLUSH, {
                "session_key": self.session.key,
                "message_count": len(to_consolidate),
            })

        self.session.last_consolidated = end
