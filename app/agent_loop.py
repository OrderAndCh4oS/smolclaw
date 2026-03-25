import inspect
import json
import time
from typing import Awaitable, Callable, Optional

from app.context_builder import ContextBuilder
from app.definitions import MAX_ITERATIONS, MEMORY_WINDOW
from app.hooks import HookRunner, ON_SESSION_START, ON_BEFORE_TURN, ON_AFTER_TURN, ON_SESSION_END
from app.logger import logger
from app.session import Session, SessionManager
from app.tools.registry import ToolRegistry
from app.usage import UsageCollector, SessionUsage, TurnUsage


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
        reflection: bool = False,
        planning: bool = False,
    ):
        self.llm = llm
        self.tool_registry = tool_registry
        self.context_builder = context_builder
        self.session = session
        self.session_manager = session_manager
        self.max_iterations = max_iterations
        self.memory_window = memory_window
        self.smol_rag = smol_rag
        self.reflection = reflection
        self.planning = planning
        self.hook_runner = hook_runner or HookRunner()
        self._stop_after_current = False
        self._session_started = False
        self._owned_resources = []
        self._closed = False
        self.session_usage = SessionUsage(session_key=session.key)
        self._usage_collector = UsageCollector()

    @staticmethod
    def _truncate_text(value: str, limit: int = 80) -> str:
        text = str(value).replace("\n", "\\n")
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    @classmethod
    def _summarize_argument_value(cls, key: str, value):
        if isinstance(value, str):
            if key in {"content", "old_text", "new_text"}:
                return f"<{len(value)} chars>"
            return cls._truncate_text(value)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return f"<list:{len(value)}>"
        if isinstance(value, dict):
            return f"<object:{len(value)}>"
        return cls._truncate_text(repr(value))

    @classmethod
    def summarize_tool_call(cls, name: str, arguments: dict) -> str:
        if not arguments:
            return name
        parts = []
        for key, value in arguments.items():
            summarized = cls._summarize_argument_value(key, value)
            parts.append(f"{key}={summarized}")
        return f"{name} " + ", ".join(parts)

    @classmethod
    def summarize_tool_result(cls, result: str, limit: int = 100) -> str:
        return cls._truncate_text(result or "", limit=limit)

    async def _emit_event(
        self,
        on_event: Optional[Callable[[dict], Awaitable[None]]],
        event: dict,
    ):
        if not on_event:
            return
        try:
            await on_event(event)
        except Exception as exc:
            logger.warning("Failed to emit agent event: %s", exc)

    async def process(
        self,
        user_content: str,
        on_output: Optional[Callable[[str], Awaitable[None]]] = None,
        on_event: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> str:
        if not self._session_started:
            self._session_started = True
            # Wire usage collector to LLM(s)
            if hasattr(self.llm, "usage_collector"):
                self.llm.usage_collector = self._usage_collector
            if self.smol_rag and hasattr(getattr(self.smol_rag, "llm", None), "usage_collector"):
                self.smol_rag.llm.usage_collector = self._usage_collector
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

        from app.tracing import trace_agent_turn

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

            turn = TurnUsage(iteration=iteration)

            # Planning prompt: nudge the agent to think before acting (first iteration only)
            if self.planning and iteration == 0:
                messages.append({
                    "role": "system",
                    "content": (
                        "Before acting, think through your approach: "
                        "What is the user asking for? What information do you need? "
                        "What's the best sequence of steps? Which tools should you use and in what order? "
                        "State your plan briefly, then execute it."
                    ),
                })

            await self._emit_event(on_event, {
                "type": "llm", "phase": "start", "iteration": iteration,
            })

            streamed_content = False

            async def _stream_chunk(text: str):
                nonlocal streamed_content
                streamed_content = True
                if on_output:
                    await on_output(text)

            with self._usage_collector.category("agent_turn"):
                llm_started = time.perf_counter()
                result = await self.llm.get_tool_completion(
                    messages=messages,
                    tools=tools,
                    stream=on_output is not None,
                    on_chunk=_stream_chunk if on_output else None,
                )
                llm_duration_ms = int((time.perf_counter() - llm_started) * 1000)

            llm_records = self._usage_collector.drain()
            turn.llm_calls.extend(llm_records)

            await self._emit_event(on_event, {
                "type": "llm", "phase": "end", "iteration": iteration,
                "duration_ms": llm_duration_ms,
                "prompt_tokens": sum(r.prompt_tokens for r in llm_records),
                "completion_tokens": sum(r.completion_tokens for r in llm_records),
                "total_tokens": sum(r.total_tokens for r in llm_records),
                "model": getattr(self.llm, "completion_model", "unknown"),
            })

            if not result["has_tool_calls"]:
                content = result["content"] or ""
                if on_output and content and not streamed_content:
                    await on_output(content)
                self.session.add_message({"role": "assistant", "content": content})
                self.session_manager.save(self.session)

                self.session_usage.turns.append(turn)

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
                summary = self.summarize_tool_call(name, arguments)
                await self._emit_event(on_event, {
                    "type": "tool",
                    "phase": "start",
                    "iteration": iteration,
                    "name": name,
                    "arguments": arguments,
                    "summary": summary,
                })

                started_at = time.perf_counter()
                with self._usage_collector.category("context_retrieval"):
                    tool_result = await self.tool_registry.execute(name, arguments)
                tool_duration_ms = int((time.perf_counter() - started_at) * 1000)
                turn.tool_duration_ms += tool_duration_ms
                ok = not str(tool_result).startswith("Error:")
                await self._emit_event(on_event, {
                    "type": "tool",
                    "phase": "end",
                    "iteration": iteration,
                    "name": name,
                    "arguments": arguments,
                    "summary": summary,
                    "ok": ok,
                    "duration_ms": tool_duration_ms,
                    "result_preview": self.summarize_tool_result(tool_result),
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result,
                })

            # Drain any usage from tool-initiated LLM calls (e.g. memory search context retrieval)
            tool_llm_records = self._usage_collector.drain()
            turn.llm_calls.extend(tool_llm_records)

            # Observation prompt: nudge the agent to interpret tool results
            if self.planning:
                messages.append({
                    "role": "system",
                    "content": (
                        "Review the tool results above. What did you learn? "
                        "Does this change your approach? Do you need more information or can you answer now?"
                    ),
                })

            # Reflection prompt: encourage self-assessment before next LLM call
            if self.reflection:
                messages.append({
                    "role": "system",
                    "content": (
                        "Before continuing, assess: Have you gathered enough information to answer completely? "
                        "Are your findings verified against sources? Is anything missing or uncertain? "
                        "If incomplete, continue working. If complete, provide your final answer."
                    ),
                })

            self.session_usage.turns.append(turn)

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

    def add_owned_resource(self, resource):
        """Register a closeable resource owned by this agent loop."""
        if resource is not None:
            self._owned_resources.append(resource)

    async def close(self):
        """Fire session end hooks and close resources owned by this agent loop."""
        if self._closed:
            return
        self._closed = True

        try:
            # Drain any remaining usage from background hooks
            self.session_usage.background_calls.extend(self._usage_collector.drain())
            self.session_usage.ended_at = time.time()
            await self.hook_runner.fire(ON_SESSION_END, {
                "session_key": self.session.key,
                "session": self.session,
                "usage": self.session_usage,
            })
        finally:
            seen = set()
            for resource in (self.llm, *self._owned_resources):
                if resource is None or id(resource) in seen:
                    continue
                seen.add(id(resource))
                close_fn = getattr(resource, "close", None)
                if not callable(close_fn):
                    continue
                try:
                    result = close_fn()
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:
                    logger.warning("Failed to close agent resource %r: %s", resource, exc)

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
            raw_text = "\n".join(text_parts)
            with self._usage_collector.category("consolidation"):
                summary = await self._summarize_for_consolidation(raw_text)
                await self.smol_rag.ingest_text(summary, source_id=f"session-{self.session.key}")
            self.session_usage.background_calls.extend(self._usage_collector.drain())

        self.session.last_consolidated = end

    async def _summarize_for_consolidation(self, raw_text: str) -> str:
        """Summarize conversation chunk into structured markdown for memory ingestion."""
        from app.prompts import get_consolidation_prompt
        try:
            summary = await self.llm.get_completion(get_consolidation_prompt(raw_text))
            return summary.strip()
        except Exception:
            # Fallback to raw text if LLM fails
            return raw_text
