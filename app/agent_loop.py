import hashlib
import inspect
import json
import time
from typing import Awaitable, Callable, Optional

from app import diagnostics
from app.behaviors import LoopBehavior, load_behaviors
from app.context_builder import ContextBuilder
from app.definitions import MAX_ITERATIONS, MEMORY_WINDOW
from app.hooks import HookRunner, ON_SESSION_START, ON_BEFORE_TURN, ON_AFTER_TURN, ON_SESSION_END
from app.logger import logger
from app.session import Session, SessionManager
from app.tools.base import (
    ACTIVE_TOOL_CALL_ID_STATE_KEY,
    ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY,
    TRACE_RECORDER_STATE_KEY,
    ToolResult,
    normalize_tool_result,
)
from app.tools.registry import ToolRegistry
from app.pricing import aggregate_cost
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
        behaviors: Optional[list[LoopBehavior]] = None,
        goal_store=None,
        safety_state=None,
        model_settings=None,
        trace_store=None,
        runtime_shared_state=None,
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
        self.behaviors = list(behaviors or [])
        self.goal_store = goal_store
        self.safety_state = safety_state
        self.model_settings = model_settings
        self.trace_store = trace_store
        self.runtime_shared_state = runtime_shared_state if runtime_shared_state is not None else {}
        if not self.behaviors:
            legacy_behavior_names = []
            if planning:
                legacy_behavior_names.append("plan")
            if reflection:
                legacy_behavior_names.append("reflect")
            self.behaviors = load_behaviors(legacy_behavior_names)
        self.hook_runner = hook_runner or HookRunner()
        self._stop_after_current = False
        self._session_started = False
        self._owned_resources = []
        self._closed = False
        self.session_usage = SessionUsage(session_key=session.key)
        self._usage_collector = UsageCollector()
        self._trace_recorder = None
        self._last_stop_reason: str | None = None

    @staticmethod
    def _truncate_text(value: str, limit: int = 80) -> str:
        text = str(value).replace("\n", "\\n")
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _record_llm_records(self, records: list) -> None:
        for record in records:
            diagnostics.record_event(
                "llm.call",
                session_key=self.session.key,
                category=record.category,
                operation=record.operation,
                model=record.model,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                total_tokens=record.total_tokens,
                duration_ms=record.duration_ms,
                cached=record.cached,
                estimated_cost=aggregate_cost([record]),
            )

    def _llm_usage_payload(self, records: list, *, current_turn: TurnUsage | None = None) -> dict:
        session_records = self.session_usage.all_records()
        if current_turn is not None:
            session_records = [*session_records, *current_turn.llm_calls]
        else:
            session_records = [*session_records, *records]
        return {
            "prompt_tokens": sum(r.prompt_tokens for r in records),
            "completion_tokens": sum(r.completion_tokens for r in records),
            "total_tokens": sum(r.total_tokens for r in records),
            "estimated_cost": aggregate_cost(records),
            "session_estimated_cost": aggregate_cost(session_records),
        }

    @staticmethod
    def _content_fingerprint(value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
        return f"<{len(value)} chars sha256={digest}>"

    @classmethod
    def _summarize_argument_value(cls, key: str, value):
        if isinstance(value, str):
            if key in {"content", "old_text", "new_text", "patch_text"}:
                return cls._content_fingerprint(value)
            if "\n" in value:
                return cls._content_fingerprint(value)
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

    @classmethod
    def summarize_tool_arguments(cls, arguments: dict) -> dict:
        return {
            key: cls._summarize_argument_value(key, value)
            for key, value in (arguments or {}).items()
        }

    @staticmethod
    def _format_tool_message_content(tool_result: ToolResult) -> str:
        content = tool_result.content or ""
        excerpt_ids = []
        seen = set()
        for excerpt_id in tool_result.metadata.get("accessed_excerpt_ids") or []:
            if not excerpt_id or excerpt_id in seen:
                continue
            seen.add(excerpt_id)
            excerpt_ids.append(excerpt_id)

        if not excerpt_ids:
            return content

        ids_block = "\n".join([
            "Excerpt IDs you can use with memory_get:",
            *[f"- {excerpt_id}" for excerpt_id in excerpt_ids],
        ])
        if not content:
            return ids_block
        return f"{content}\n\n{ids_block}"

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

    def _trace_append(
        self,
        event: str,
        data: dict | None = None,
        *,
        turn_index: int | None = None,
        iteration: int | None = None,
    ):
        if self._trace_recorder is None:
            return None
        try:
            return self._trace_recorder.append(
                event,
                data or {},
                turn_index=turn_index,
                iteration=iteration,
            )
        except Exception as exc:
            logger.warning("Failed to append run trace event %s: %s", event, exc)
            return None

    def _start_trace(self, user_content: str):
        if self.trace_store is None:
            return None
        goal = self.goal_store.load(self.session.key) if self.goal_store is not None else None
        recorder = self.trace_store.start_run(
            self.session.key,
            goal_id=getattr(goal, "goal_id", None),
            metadata={
                "message_length": len(user_content or ""),
                "model": getattr(self.llm, "completion_model", "unknown"),
                "has_active_goal": bool(goal is not None and goal.status == "active"),
            },
        )
        self._trace_recorder = recorder
        self.runtime_shared_state[TRACE_RECORDER_STATE_KEY] = recorder
        return recorder

    def _finish_trace(self, status: str, stop_reason: str | None = None):
        recorder = self._trace_recorder
        if recorder is None:
            return
        try:
            recorder.finish(status, stop_reason=stop_reason)
        except Exception as exc:
            logger.warning("Failed to finish run trace: %s", exc)
        finally:
            self._trace_recorder = None
            self.runtime_shared_state.pop(TRACE_RECORDER_STATE_KEY, None)

    def _pending_approval_count(self) -> int:
        approval_store = self.runtime_shared_state.get("approval_store")
        if approval_store is None:
            return 0
        list_fn = getattr(approval_store, "list", None)
        if not callable(list_fn):
            return 0
        try:
            return len(list_fn(self.session.key, status="pending"))
        except Exception:
            return 0

    def _mark_goal_loop_started(self, run_id: str | None):
        if self.goal_store is None:
            return
        mark = getattr(self.goal_store, "mark_loop_started", None)
        if not callable(mark):
            return
        try:
            mark(self.session.key, run_id=run_id)
        except Exception as exc:
            logger.warning("Failed to mark goal loop started: %s", exc)

    def _mark_goal_loop_finished(self, stop_reason: str):
        if self.goal_store is None:
            return
        mark = getattr(self.goal_store, "mark_loop_finished", None)
        if not callable(mark):
            return
        try:
            mark(
                self.session.key,
                stop_reason=stop_reason,
                pending_approvals=self._pending_approval_count(),
            )
        except Exception as exc:
            logger.warning("Failed to mark goal loop finished: %s", exc)

    async def _invoke_tool(self, name: str, arguments: dict) -> ToolResult:
        invoke = getattr(self.tool_registry, "invoke", None)
        if callable(invoke):
            maybe_result = invoke(name, arguments)
            if inspect.isawaitable(maybe_result):
                return normalize_tool_result(await maybe_result)
        return normalize_tool_result(await self.tool_registry.execute(name, arguments))

    def _goal_context_message(self) -> dict | None:
        if self.goal_store is None:
            return None
        goal = self.goal_store.load(self.session.key)
        if goal is None or goal.status != "active":
            return None
        return {"role": "system", "content": goal.render_for_prompt()}

    async def process(
        self,
        user_content: str,
        on_output: Optional[Callable[[str], Awaitable[None]]] = None,
        on_event: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> str:
        diagnostics.record_event(
            "agent.turn.start",
            session_key=self.session.key,
            message_length=len(user_content or ""),
            model=getattr(self.llm, "completion_model", "unknown"),
        )
        self._last_stop_reason = None
        recorder = self._start_trace(user_content)
        self._mark_goal_loop_started(getattr(recorder, "run_id", None))
        turn_index = len(self.session_usage.turns)
        self._trace_append("turn.started", {
            "message_length": len(user_content or ""),
        }, turn_index=turn_index)
        started_at = time.perf_counter()
        try:
            response = await self._process_impl(user_content, on_output=on_output, on_event=on_event)
        except Exception as exc:
            self._trace_append("error", {
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            }, turn_index=turn_index)
            incident_id = diagnostics.record_exception(
                exc,
                boundary="agent_loop",
                session_key=self.session.key,
                model=getattr(self.llm, "completion_model", "unknown"),
            )
            diagnostics.record_event(
                "agent.error",
                session_key=self.session.key,
                incident_id=incident_id,
            )
            self._mark_goal_loop_finished("error")
            self._finish_trace("error", stop_reason="error")
            raise
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        diagnostics.record_event(
            "agent.turn.end",
            session_key=self.session.key,
            duration_ms=duration_ms,
            response_length=len(response or ""),
            total_tokens=self.session_usage.total_tokens,
        )
        stop_reason = self._last_stop_reason or "assistant_final"
        self._trace_append("turn.ended", {
            "duration_ms": duration_ms,
            "response_length": len(response or ""),
            "total_tokens": self.session_usage.total_tokens,
            "stop_reason": stop_reason,
        }, turn_index=turn_index)
        trace_status = "stopped" if stop_reason in {"max_iterations", "stop_requested"} else "complete"
        self._mark_goal_loop_finished(stop_reason)
        self._finish_trace(trace_status, stop_reason=stop_reason)
        if recorder is not None:
            diagnostics.record_event(
                "agent.trace",
                session_key=self.session.key,
                run_id=recorder.run_id,
                trace_path=recorder.summary.trace_path,
            )
        return response

    async def _process_impl(
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

        self._begin_safety_task()

        self.session.add_message({"role": "user", "content": user_content})
        if self.goal_store is not None:
            self.goal_store.increment_turn_count(self.session.key)

        await self._maybe_consolidate()

        history = self.session.get_history(self.memory_window)
        # Remove the last user message from history since build_messages adds it
        if history and history[-1]["role"] == "user" and history[-1]["content"] == user_content:
            history = history[:-1]

        messages = await self.context_builder.build_messages_async(
            history=history,
            user_content=user_content,
        )
        goal_message = self._goal_context_message()
        if goal_message is not None:
            messages.insert(1 if messages and messages[0].get("role") == "system" else 0, goal_message)

        from app.tracing import get_tracer

        for iteration in range(self.max_iterations):
            _turn_span = get_tracer().start_span(f"agent.turn.{iteration}")
            _turn_span.set_attribute("agent.session_key", self.session.key)
            _turn_span.set_attribute("agent.iteration", iteration)
            _turn_span.set_attribute("agent.model", getattr(self.llm, "completion_model", "unknown"))

            if self._stop_after_current:
                msg = "Stopped: time limit reached."
                self.session.add_message({"role": "assistant", "content": msg})
                self.session_manager.save(self.session)
                _turn_span.end()
                self._last_stop_reason = "stop_requested"
                return msg

            await self.hook_runner.fire(ON_BEFORE_TURN, {
                "iteration": iteration,
                "session_key": self.session.key,
                "user_content": user_content,
            })

            turn = TurnUsage(iteration=iteration)

            if iteration == 0:
                for behavior in self.behaviors:
                    if behavior.before_first_llm_prompt:
                        messages.append({
                            "role": "system",
                            "content": behavior.before_first_llm_prompt,
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

            tools = self.tool_registry.get_definitions() or None
            current_turn_index = len(self.session_usage.turns)
            self._trace_append("llm.started", {
                "model": getattr(self.llm, "completion_model", "unknown"),
                "tools_count": len(tools or []),
            }, turn_index=current_turn_index, iteration=iteration)

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
            self._record_llm_records(llm_records)
            usage_payload = self._llm_usage_payload(llm_records, current_turn=turn)

            await self._emit_event(on_event, {
                "type": "llm", "phase": "end", "iteration": iteration,
                "duration_ms": llm_duration_ms,
                "has_tool_calls": bool(result["has_tool_calls"]),
                "model": getattr(self.llm, "completion_model", "unknown"),
                **usage_payload,
            })
            self._trace_append("llm.ended", {
                "duration_ms": llm_duration_ms,
                "has_tool_calls": bool(result["has_tool_calls"]),
                "model": getattr(self.llm, "completion_model", "unknown"),
                **usage_payload,
            }, turn_index=current_turn_index, iteration=iteration)

            if not result["has_tool_calls"]:
                content = result["content"] or ""
                if on_output and content and not streamed_content:
                    await on_output(content)
                self.session.add_message({"role": "assistant", "content": content})
                self.session_manager.save(self.session)
                self._last_stop_reason = "assistant_final"

                self.session_usage.turns.append(turn)

                await self.hook_runner.fire(ON_AFTER_TURN, {
                    "iteration": iteration,
                    "session_key": self.session.key,
                    "response": content,
                    "had_tool_calls": False,
                })
                _turn_span.end()
                return content

            # Process tool calls
            assistant_msg = {"role": "assistant", "content": result["content"]}
            if result.get("response_items"):
                assistant_msg["response_items"] = result["response_items"]
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
                tool_started_event = self._trace_append("tool.started", {
                    "name": name,
                    "arguments": self.summarize_tool_arguments(arguments),
                    "summary": summary,
                    "command": arguments.get("command"),
                }, turn_index=current_turn_index, iteration=iteration)

                started_at = time.perf_counter()
                previous_tool_trace_event_id = self.runtime_shared_state.get(
                    ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY,
                )
                previous_tool_call_id = self.runtime_shared_state.get(ACTIVE_TOOL_CALL_ID_STATE_KEY)
                if tool_started_event is not None:
                    self.runtime_shared_state[ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY] = (
                        tool_started_event.event_id
                    )
                if tool_call.get("id"):
                    self.runtime_shared_state[ACTIVE_TOOL_CALL_ID_STATE_KEY] = tool_call["id"]
                try:
                    with self._usage_collector.category("context_retrieval"):
                        tool_result = await self._invoke_tool(name, arguments)
                finally:
                    if previous_tool_trace_event_id is None:
                        self.runtime_shared_state.pop(ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY, None)
                    else:
                        self.runtime_shared_state[ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY] = (
                            previous_tool_trace_event_id
                        )
                    if previous_tool_call_id is None:
                        self.runtime_shared_state.pop(ACTIVE_TOOL_CALL_ID_STATE_KEY, None)
                    else:
                        self.runtime_shared_state[ACTIVE_TOOL_CALL_ID_STATE_KEY] = (
                            previous_tool_call_id
                        )
                tool_duration_ms = int((time.perf_counter() - started_at) * 1000)
                turn.tool_duration_ms += tool_duration_ms
                ok = tool_result.ok
                await self._emit_event(on_event, {
                    "type": "tool",
                    "phase": "end",
                    "iteration": iteration,
                    "name": name,
                    "arguments": arguments,
                    "summary": summary,
                    "ok": ok,
                    "duration_ms": tool_duration_ms,
                    "status": tool_result.status,
                    "result_preview": self.summarize_tool_result(tool_result.content),
                })
                tool_event_data = {
                    "name": name,
                    "arguments": self.summarize_tool_arguments(arguments),
                    "summary": summary,
                    "ok": ok,
                    "duration_ms": tool_duration_ms,
                    "status": tool_result.status,
                    "result_preview": self.summarize_tool_result(tool_result.content),
                }
                self._trace_append(
                    "tool.ended",
                    tool_event_data,
                    turn_index=current_turn_index,
                    iteration=iteration,
                )
                if tool_result.status == "denied" or "not permitted" in tool_result.content:
                    self._trace_append(
                        "tool.denied",
                        tool_event_data,
                        turn_index=current_turn_index,
                        iteration=iteration,
                    )
                if "safety gate blocked" in tool_result.content:
                    self._trace_append(
                        "safety.blocked",
                        tool_event_data,
                        turn_index=current_turn_index,
                        iteration=iteration,
                    )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": self._format_tool_message_content(tool_result),
                })

            # Drain any usage from tool-initiated LLM calls (e.g. memory search context retrieval)
            tool_llm_records = self._usage_collector.drain()
            turn.llm_calls.extend(tool_llm_records)
            self._record_llm_records(tool_llm_records)
            if tool_llm_records:
                await self._emit_event(on_event, {
                    "type": "llm",
                    "phase": "end",
                    "iteration": iteration,
                    "duration_ms": sum(r.duration_ms for r in tool_llm_records),
                    "has_tool_calls": True,
                    "model": ",".join(sorted({r.model for r in tool_llm_records})),
                    "background": True,
                    **self._llm_usage_payload(tool_llm_records, current_turn=turn),
                })

            for behavior in self.behaviors:
                if behavior.after_tools_prompt:
                    messages.append({
                        "role": "system",
                        "content": behavior.after_tools_prompt,
                    })

            self.session_usage.turns.append(turn)

            await self.hook_runner.fire(ON_AFTER_TURN, {
                "iteration": iteration,
                "session_key": self.session.key,
                "tool_calls": [tc["name"] for tc in result["tool_calls"]],
                "had_tool_calls": True,
            })
            _turn_span.end()

        # Exceeded max iterations
        finalized = await self._finalize_after_max_iterations(
            messages,
            on_output=on_output,
            on_event=on_event,
        )
        if finalized is not None:
            return finalized

        msg = (
            "Stopped: reached max iterations without a final response. "
            "A finalization pass could not produce a plain assistant response."
        )
        self.session.add_message({"role": "assistant", "content": msg})
        self.session_manager.save(self.session)
        self._last_stop_reason = "max_iterations"
        return msg

    async def _finalize_after_max_iterations(
        self,
        messages: list[dict],
        *,
        on_output: Optional[Callable[[str], Awaitable[None]]] = None,
        on_event: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> str | None:
        final_messages = list(messages)
        final_messages.append({
            "role": "system",
            "content": (
                "The tool iteration limit has been reached. Do not call tools. "
                "Provide a concise final response that summarizes completed work, "
                "verification, blockers, and the next best step."
            ),
        })
        iteration = self.max_iterations
        turn = TurnUsage(iteration=iteration)
        current_turn_index = len(self.session_usage.turns)

        await self._emit_event(on_event, {
            "type": "llm",
            "phase": "start",
            "iteration": iteration,
            "finalization": True,
        })
        self._trace_append("llm.started", {
            "model": getattr(self.llm, "completion_model", "unknown"),
            "tools_count": 0,
            "finalization": True,
        }, turn_index=current_turn_index, iteration=iteration)

        try:
            with self._usage_collector.category("agent_turn"):
                llm_started = time.perf_counter()
                result = await self.llm.get_tool_completion(
                    messages=final_messages,
                    tools=None,
                    stream=False,
                    on_chunk=None,
                )
                llm_duration_ms = int((time.perf_counter() - llm_started) * 1000)
        except Exception as exc:
            self._trace_append("finalization.failed", {
                "error_type": exc.__class__.__name__,
                "message": str(exc),
            }, turn_index=current_turn_index, iteration=iteration)
            return None

        llm_records = self._usage_collector.drain()
        turn.llm_calls.extend(llm_records)
        self._record_llm_records(llm_records)
        usage_payload = self._llm_usage_payload(llm_records, current_turn=turn)

        await self._emit_event(on_event, {
            "type": "llm",
            "phase": "end",
            "iteration": iteration,
            "duration_ms": llm_duration_ms,
            "has_tool_calls": bool(result["has_tool_calls"]),
            "model": getattr(self.llm, "completion_model", "unknown"),
            "finalization": True,
            **usage_payload,
        })
        self._trace_append("llm.ended", {
            "duration_ms": llm_duration_ms,
            "has_tool_calls": bool(result["has_tool_calls"]),
            "model": getattr(self.llm, "completion_model", "unknown"),
            "finalization": True,
            **usage_payload,
        }, turn_index=current_turn_index, iteration=iteration)

        if result["has_tool_calls"]:
            self.session_usage.turns.append(turn)
            self._trace_append("finalization.failed", {
                "reason": "requested_tools",
            }, turn_index=current_turn_index, iteration=iteration)
            return None

        content = result["content"] or ""
        if not content.strip():
            self.session_usage.turns.append(turn)
            self._trace_append("finalization.failed", {
                "reason": "empty_response",
            }, turn_index=current_turn_index, iteration=iteration)
            return None

        if on_output:
            await on_output(content)
        self.session.add_message({"role": "assistant", "content": content})
        self.session_manager.save(self.session)
        self._last_stop_reason = "max_iterations_finalized"
        self.session_usage.turns.append(turn)
        await self.hook_runner.fire(ON_AFTER_TURN, {
            "iteration": iteration,
            "session_key": self.session.key,
            "response": content,
            "had_tool_calls": False,
            "finalization": True,
        })
        return content

    def _begin_safety_task(self):
        if self.safety_state is None:
            return
        goal = self.goal_store.load(self.session.key) if self.goal_store is not None else None
        if goal is not None and goal.status == "active":
            task_key = f"goal:{self.session.key}:{goal.created_at}:{goal.objective}"
        else:
            task_key = f"turn:{self.session.key}:{len(self.session.messages)}"
        self.safety_state.begin_task(task_key)

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
