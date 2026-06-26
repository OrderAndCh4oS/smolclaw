from app.runtime_state import (
    APPROVAL_STORE_STATE_KEY,
    RuntimeSharedState,
    SESSION_KEY_STATE_KEY,
)
from app.tools.base import (
    ACTIVE_TOOL_CALL_ID_STATE_KEY,
    ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY,
    TRACE_RECORDER_STATE_KEY,
)


def test_runtime_shared_state_preserves_dict_wire_format():
    values = {}
    state = RuntimeSharedState(values)
    recorder = object()
    approval_store = object()

    state.trace_recorder = recorder
    state.session_key = "session-a"
    state.approval_store = approval_store

    assert values[TRACE_RECORDER_STATE_KEY] is recorder
    assert values[SESSION_KEY_STATE_KEY] == "session-a"
    assert values[APPROVAL_STORE_STATE_KEY] is approval_store
    assert RuntimeSharedState(values).trace_recorder is recorder
    assert RuntimeSharedState(values).session_key == "session-a"


def test_runtime_shared_state_scoped_tool_call_restores_previous_values():
    values = {
        ACTIVE_TOOL_CALL_ID_STATE_KEY: "call-before",
        ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY: "trace-before",
    }
    state = RuntimeSharedState(values)

    with state.scoped_tool_call(tool_call_id="call-during", tool_trace_event_id="trace-during"):
        assert state.active_tool_ids == ("call-during", "trace-during")

    assert state.active_tool_ids == ("call-before", "trace-before")


def test_runtime_shared_state_scoped_tool_call_clears_new_values():
    values = {}
    state = RuntimeSharedState(values)

    with state.scoped_tool_call(tool_call_id="call-during", tool_trace_event_id="trace-during"):
        assert values[ACTIVE_TOOL_CALL_ID_STATE_KEY] == "call-during"

    assert ACTIVE_TOOL_CALL_ID_STATE_KEY not in values
    assert ACTIVE_TOOL_TRACE_EVENT_ID_STATE_KEY not in values


def test_runtime_shared_state_approved_command_bypass_restores_previous_value():
    values = {}
    state = RuntimeSharedState(values)

    with state.approved_command_bypass():
        assert state.allow_denied_command_once is True

    assert state.allow_denied_command_once is False
