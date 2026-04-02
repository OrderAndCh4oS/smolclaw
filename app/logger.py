import logging
import os.path
import os
import re
from logging.handlers import RotatingFileHandler

from app.definitions import LOG_DIR

logger = logging.getLogger("mini-rag")
_HANDLER_NAME = "smolclaw-log-file"
_LOG_FILE_PATTERN = re.compile(r"^.+\.log(?:\.\d+)?$")


def _get_configured_int(env_var: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(env_var, str(default))))
    except ValueError:
        return default


def _iter_file_handlers():
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            yield handler


def _clear_file_handlers():
    for handler in list(_iter_file_handlers()):
        logger.removeHandler(handler)
        handler.close()


def _is_log_filename(name: str) -> bool:
    return bool(_LOG_FILE_PATTERN.match(name))


def clear_logs(log_dir: str = LOG_DIR) -> list[str]:
    """Delete all files in the log directory and detach open file handlers."""
    _clear_file_handlers()
    if not os.path.isdir(log_dir):
        return []

    deleted = []
    for name in sorted(os.listdir(log_dir)):
        path = os.path.join(log_dir, name)
        if not os.path.isfile(path) or not _is_log_filename(name):
            continue
        os.remove(path)
        deleted.append(path)
    return deleted


def set_logger(log_file: str, log_dir: str | None = None):
    configured_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, configured_level, logging.INFO)
    logger.setLevel(log_level)
    log_dir = log_dir or LOG_DIR
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)
    max_bytes = _get_configured_int("LOG_MAX_BYTES", 10 * 1024 * 1024)
    backup_count = _get_configured_int("LOG_BACKUP_COUNT", 5)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    existing_handler = None
    for handler in _iter_file_handlers():
        if getattr(handler, "name", None) == _HANDLER_NAME:
            existing_handler = handler
            break

    if (
        existing_handler is None
        or getattr(existing_handler, "baseFilename", None) != os.path.abspath(log_path)
        or getattr(existing_handler, "maxBytes", None) != max_bytes
        or getattr(existing_handler, "backupCount", None) != backup_count
    ):
        _clear_file_handlers()
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.name = _HANDLER_NAME
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        existing_handler = file_handler

    existing_handler.setLevel(log_level)
