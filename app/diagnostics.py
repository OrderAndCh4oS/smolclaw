"""Workspace-local diagnostics: logs, structured events, and incidents."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import traceback
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_HANDLER_NAME = "smolclaw-diagnostics-file"
_EVENTS_FILE = "events.jsonl"
_DEFAULT_LOG_FILE = "smolclaw.log"
_configured_log_dir: Path | None = None
_event_path: Path | None = None

logging.getLogger("app.diagnostics").addHandler(logging.NullHandler())

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token|authorization|auth|secret|password|credential)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|sk-ant-[A-Za-z0-9_-]{12,}|"
    r"BSA[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,})\b"
)


def _configured_int(env_var: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(env_var, str(default))))
    except ValueError:
        return default


def configure(log_dir: str | os.PathLike[str], *, log_file: str = _DEFAULT_LOG_FILE) -> Path:
    """Configure workspace-local diagnostics and return the events JSONL path."""
    global _configured_log_dir, _event_path

    resolved_log_dir = Path(log_dir).expanduser().resolve()
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    _configured_log_dir = resolved_log_dir
    _event_path = resolved_log_dir / _EVENTS_FILE

    log_path = resolved_log_dir / log_file
    max_bytes = _configured_int("LOG_MAX_BYTES", 10 * 1024 * 1024)
    backup_count = _configured_int("LOG_BACKUP_COUNT", 5)
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    for logger_name in ("app", "smolclaw", "smolclaw.rag"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.propagate = False
        existing = next(
            (
                handler for handler in logger.handlers
                if getattr(handler, "name", None) == _HANDLER_NAME
            ),
            None,
        )
        if (
            existing is None
            or getattr(existing, "baseFilename", None) != str(log_path)
            or getattr(existing, "maxBytes", None) != max_bytes
            or getattr(existing, "backupCount", None) != backup_count
        ):
            if existing is not None:
                logger.removeHandler(existing)
                existing.close()
            handler = RotatingFileHandler(
                log_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            handler.name = _HANDLER_NAME
            handler.setFormatter(formatter)
            handler.setLevel(level)
            logger.addHandler(handler)
        else:
            existing.setLevel(level)

    return _event_path


def event_path() -> Path | None:
    return _event_path


def redact(value: Any, *, max_string: int = 500) -> Any:
    """Return a log-safe copy of common Python values."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            text_key = str(key)
            redacted[text_key] = "[REDACTED]" if _SECRET_KEY_RE.search(text_key) else redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value[:20]]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value[:20])
    if isinstance(value, str):
        safe = _SECRET_VALUE_RE.sub("[REDACTED]", value)
        if len(safe) > max_string:
            return safe[: max_string - 15] + "...<truncated>"
        return safe
    return value


def record_event(event_type: str, **fields) -> dict:
    event = {
        "timestamp": time.time(),
        "event": event_type,
        **redact(fields),
    }
    if _event_path is not None:
        try:
            with _event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        except Exception:
            logging.getLogger("app.diagnostics").debug(
                "failed to write diagnostics event", exc_info=True
            )
    return event


def record_exception(
    exc: BaseException,
    *,
    boundary: str,
    user_message: str | None = None,
    **fields,
) -> str:
    incident_id = f"inc-{uuid.uuid4().hex[:10]}"
    message = redact(user_message or str(exc) or exc.__class__.__name__)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    record_event(
        "error",
        incident_id=incident_id,
        boundary=boundary,
        error_type=exc.__class__.__name__,
        message=message,
        traceback=tb,
        **fields,
    )
    logging.getLogger("app.diagnostics").error(
        "incident %s boundary=%s error=%s",
        incident_id,
        boundary,
        message,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return incident_id


def user_error_message(incident_id: str, message: str | None = None) -> str:
    if message:
        return f"Error: incident {incident_id} - {redact(message)}"
    return f"Error: incident {incident_id}"
