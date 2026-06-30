"""Typed accessors for per-loop shared runtime state."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, MutableMapping

from app.execution_grants import ExecutionGrant

from app.tools.base import (
    ACTIVE_TOOL_CALL_ID_STATE_KEY,
    ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY,
    TRACE_RECORDER_STATE_KEY,
)


SESSION_KEY_STATE_KEY = "session_key"
APPROVAL_CONTEXT_KEY_STATE_KEY = "approval_context_key"
SAFETY_STATE_KEY = "safety_state"
TRACE_STORE_STATE_KEY = "trace_store"
APPROVAL_STORE_STATE_KEY = "approval_store"
PERMISSION_CONTROLLER_STATE_KEY = "permission_controller"
EVENT_SINK_STATE_KEY = "event_sink"
CHECKPOINT_STORE_STATE_KEY = "checkpoint_store"
PERMISSION_POLICY_STATE_KEY = "permission_policy"
ALLOW_DENIED_COMMAND_ONCE_STATE_KEY = "allow_denied_command_once"
ACTIVE_EXECUTION_GRANT_STATE_KEY = "active_execution_grant"


@dataclass(frozen=True)
class RuntimeInvocationContext:
    """Typed snapshot of cross-component invocation state."""

    trace_recorder: Any = None
    session_key: str | None = None
    approval_context_key: str | None = None
    approval_store: Any = None
    permission_controller: Any = None
    event_sink: Any = None
    checkpoint_store: Any = None
    trace_store: Any = None
    safety_state: Any = None
    permission_policy: Any = None
    active_tool_call_id: str | None = None
    active_tool_trace_event_id: str | None = None
    active_execution_grant: ExecutionGrant | None = None
    allow_denied_command_once: bool = False


@dataclass
class RuntimeSharedState:
    """Stable facade over the runtime shared-state dictionary.

    The dictionary remains the compatibility wire format for existing tools and
    tests. Runtime code should use this facade for known cross-component keys.
    """

    values: MutableMapping[str, Any]

    @property
    def trace_recorder(self):
        return self.values.get(TRACE_RECORDER_STATE_KEY)

    @trace_recorder.setter
    def trace_recorder(self, recorder) -> None:
        self._set_or_clear(TRACE_RECORDER_STATE_KEY, recorder)

    @property
    def session_key(self) -> str | None:
        value = self.values.get(SESSION_KEY_STATE_KEY)
        return str(value) if value else None

    @session_key.setter
    def session_key(self, value: str | None) -> None:
        self._set_or_clear(SESSION_KEY_STATE_KEY, value)

    @property
    def approval_context_key(self) -> str | None:
        value = self.values.get(APPROVAL_CONTEXT_KEY_STATE_KEY)
        if value:
            return str(value)
        return self.session_key

    @approval_context_key.setter
    def approval_context_key(self, value: str | None) -> None:
        self._set_or_clear(APPROVAL_CONTEXT_KEY_STATE_KEY, value)

    @property
    def approval_store(self):
        return self.values.get(APPROVAL_STORE_STATE_KEY)

    @approval_store.setter
    def approval_store(self, store) -> None:
        self._set_or_clear(APPROVAL_STORE_STATE_KEY, store)

    @property
    def permission_controller(self):
        return self.values.get(PERMISSION_CONTROLLER_STATE_KEY)

    @permission_controller.setter
    def permission_controller(self, controller) -> None:
        self._set_or_clear(PERMISSION_CONTROLLER_STATE_KEY, controller)

    @property
    def event_sink(self):
        return self.values.get(EVENT_SINK_STATE_KEY)

    @event_sink.setter
    def event_sink(self, sink) -> None:
        self._set_or_clear(EVENT_SINK_STATE_KEY, sink)

    @property
    def checkpoint_store(self):
        return self.values.get(CHECKPOINT_STORE_STATE_KEY)

    @checkpoint_store.setter
    def checkpoint_store(self, store) -> None:
        self._set_or_clear(CHECKPOINT_STORE_STATE_KEY, store)

    @property
    def trace_store(self):
        return self.values.get(TRACE_STORE_STATE_KEY)

    @trace_store.setter
    def trace_store(self, store) -> None:
        self._set_or_clear(TRACE_STORE_STATE_KEY, store)

    @property
    def safety_state(self):
        return self.values.get(SAFETY_STATE_KEY)

    @safety_state.setter
    def safety_state(self, state) -> None:
        self._set_or_clear(SAFETY_STATE_KEY, state)

    @property
    def permission_policy(self):
        return self.values.get(PERMISSION_POLICY_STATE_KEY)

    @permission_policy.setter
    def permission_policy(self, policy) -> None:
        self._set_or_clear(PERMISSION_POLICY_STATE_KEY, policy)

    @property
    def active_tool_call_id(self) -> str | None:
        value = self.values.get(ACTIVE_TOOL_CALL_ID_STATE_KEY)
        return str(value) if value else None

    @active_tool_call_id.setter
    def active_tool_call_id(self, value: str | None) -> None:
        self._set_or_clear(ACTIVE_TOOL_CALL_ID_STATE_KEY, value)

    @property
    def active_tool_trace_event_id(self) -> str | None:
        value = self.values.get(ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY)
        return str(value) if value else None

    @active_tool_trace_event_id.setter
    def active_tool_trace_event_id(self, value: str | None) -> None:
        self._set_or_clear(ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY, value)

    @property
    def active_tool_ids(self) -> tuple[str | None, str | None]:
        return self.active_tool_call_id, self.active_tool_trace_event_id

    @property
    def allow_denied_command_once(self) -> bool:
        return bool(self.values.get(ALLOW_DENIED_COMMAND_ONCE_STATE_KEY))

    @property
    def active_execution_grant(self):
        return self.values.get(ACTIVE_EXECUTION_GRANT_STATE_KEY)

    @property
    def invocation_context(self) -> RuntimeInvocationContext:
        grant = self.active_execution_grant
        if grant is not None and not isinstance(grant, ExecutionGrant):
            raise TypeError(
                "Runtime shared state key "
                f"'{ACTIVE_EXECUTION_GRANT_STATE_KEY}' expected ExecutionGrant, got {type(grant).__name__}."
            )
        return RuntimeInvocationContext(
            trace_recorder=self.trace_recorder,
            session_key=self.session_key,
            approval_context_key=self.approval_context_key,
            approval_store=self.approval_store,
            permission_controller=self.permission_controller,
            event_sink=self.event_sink,
            checkpoint_store=self.checkpoint_store,
            trace_store=self.trace_store,
            safety_state=self.safety_state,
            permission_policy=self.permission_policy,
            active_tool_call_id=self.active_tool_call_id,
            active_tool_trace_event_id=self.active_tool_trace_event_id,
            active_execution_grant=grant,
            allow_denied_command_once=self.allow_denied_command_once,
        )

    def get_typed(self, key: str, expected_type: type, default=None):
        value = self.values.get(key, default)
        if value is default or isinstance(value, expected_type):
            return value
        raise TypeError(f"Runtime shared state key '{key}' expected {expected_type.__name__}, got {type(value).__name__}.")

    def require_typed(self, key: str, expected_type: type):
        if key not in self.values:
            raise KeyError(f"Runtime shared state key '{key}' is not set.")
        return self.get_typed(key, expected_type)

    @contextmanager
    def scoped_tool_call(
        self,
        *,
        tool_call_id: str | None = None,
        tool_trace_event_id: str | None = None,
    ):
        previous_trace_event_id = self.values.get(ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY)
        previous_call_id = self.values.get(ACTIVE_TOOL_CALL_ID_STATE_KEY)
        if tool_trace_event_id:
            self.values[ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY] = tool_trace_event_id
        if tool_call_id:
            self.values[ACTIVE_TOOL_CALL_ID_STATE_KEY] = tool_call_id
        try:
            yield
        finally:
            self._restore(ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY, previous_trace_event_id)
            self._restore(ACTIVE_TOOL_CALL_ID_STATE_KEY, previous_call_id)

    @contextmanager
    def approved_command_bypass(self):
        previous = self.values.get(ALLOW_DENIED_COMMAND_ONCE_STATE_KEY)
        self.values[ALLOW_DENIED_COMMAND_ONCE_STATE_KEY] = True
        try:
            yield
        finally:
            self._restore(ALLOW_DENIED_COMMAND_ONCE_STATE_KEY, previous)

    @contextmanager
    def scoped_execution_grant(self, grant: ExecutionGrant):
        previous = self.values.get(ACTIVE_EXECUTION_GRANT_STATE_KEY)
        self.values[ACTIVE_EXECUTION_GRANT_STATE_KEY] = grant
        try:
            yield
        finally:
            self._restore(ACTIVE_EXECUTION_GRANT_STATE_KEY, previous)

    @contextmanager
    def scoped_event_sink(self, sink):
        previous = self.values.get(EVENT_SINK_STATE_KEY)
        self._set_or_clear(EVENT_SINK_STATE_KEY, sink)
        try:
            yield
        finally:
            self._restore(EVENT_SINK_STATE_KEY, previous)

    def _set_or_clear(self, key: str, value) -> None:
        if value is None:
            self.values.pop(key, None)
        else:
            self.values[key] = value

    def _restore(self, key: str, previous) -> None:
        if previous is None:
            self.values.pop(key, None)
        else:
            self.values[key] = previous
