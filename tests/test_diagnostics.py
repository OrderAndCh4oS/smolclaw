import json
import os

from app import diagnostics
from app.logger import clear_logs


def test_record_event_writes_workspace_jsonl(temp_dir):
    diagnostics.configure(temp_dir)

    event = diagnostics.record_event("tool.start", token="sk-secret-value-123456789")

    assert event["token"] == "[REDACTED]"
    events_path = diagnostics.event_path()
    assert events_path is not None
    rows = events_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["event"] == "tool.start"
    assert payload["token"] == "[REDACTED]"


def test_record_exception_returns_incident_and_persists_traceback(temp_dir):
    diagnostics.configure(temp_dir)

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        incident_id = diagnostics.record_exception(exc, boundary="test")

    assert incident_id.startswith("inc-")
    rows = diagnostics.event_path().read_text(encoding="utf-8").splitlines()
    payload = json.loads(rows[-1])
    assert payload["event"] == "error"
    assert payload["incident_id"] == incident_id
    assert payload["boundary"] == "test"
    assert "RuntimeError: boom" in payload["traceback"]


def test_clear_logs_removes_diagnostics_jsonl(temp_dir):
    diagnostics.configure(temp_dir)
    diagnostics.record_event("test.event")

    deleted = clear_logs(temp_dir)

    assert any(os.path.basename(path) == "events.jsonl" for path in deleted)
    assert not os.path.exists(os.path.join(temp_dir, "events.jsonl"))


def test_redact_nested_secrets_and_long_values():
    value = {
        "Authorization": "Bearer abcdefghijklmnop",
        "nested": {"api_key": "sk-proj-secretsecretsecret"},
        "content": "x" * 700,
    }

    redacted = diagnostics.redact(value)

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["content"].endswith("...<truncated>")
