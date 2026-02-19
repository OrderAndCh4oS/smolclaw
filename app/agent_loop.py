import json
from typing import Optional

from app.context_builder import ContextBuilder
from app.definitions import MAX_ITERATIONS, MEMORY_WINDOW
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
    ):
        self.llm = llm
        self.tool_registry = tool_registry
        self.context_builder = context_builder
        self.session = session
        self.session_manager = session_manager
        self.max_iterations = max_iterations
        self.memory_window = memory_window
        self.smol_rag = smol_rag

    async def process(self, user_content: str) -> str:
        self.session.add_message({"role": "user", "content": user_content})

        await self._maybe_consolidate()

        history = self.session.get_history(self.memory_window)
        # Remove the last user message from history since build_messages adds it
        if history and history[-1]["role"] == "user" and history[-1]["content"] == user_content:
            history = history[:-1]

        messages = self.context_builder.build_messages(
            history=history,
            user_content=user_content,
        )

        tools = self.tool_registry.get_definitions() or None

        for iteration in range(self.max_iterations):
            result = await self.llm.get_tool_completion(
                messages=messages,
                tools=tools,
            )

            if not result["has_tool_calls"]:
                content = result["content"] or ""
                self.session.add_message({"role": "assistant", "content": content})
                self.session_manager.save(self.session)
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

        # Exceeded max iterations
        msg = "Stopped: reached max iterations without a final response."
        self.session.add_message({"role": "assistant", "content": msg})
        self.session_manager.save(self.session)
        return msg

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

        self.session.last_consolidated = end
