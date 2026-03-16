import logging
import os

from app import logger as logger_module


def _flush_handlers():
    for handler in logger_module.logger.handlers:
        handler.flush()


class TestLoggerManagement:
    def teardown_method(self):
        logger_module.clear_logs(logger_module.LOG_DIR)
        logger_module.logger.handlers.clear()

    def test_set_logger_rotates_when_log_exceeds_max_bytes(self, monkeypatch, temp_dir):
        monkeypatch.setattr(logger_module, "LOG_DIR", temp_dir)
        monkeypatch.setenv("LOG_MAX_BYTES", "256")
        monkeypatch.setenv("LOG_BACKUP_COUNT", "2")

        logger_module.set_logger("main.log")

        for index in range(20):
            logger_module.logger.info("line-%s %s", index, "x" * 80)
        _flush_handlers()

        files = sorted(os.listdir(temp_dir))
        assert "main.log" in files
        assert any(name.startswith("main.log.") for name in files)

    def test_clear_logs_removes_files_and_detaches_handlers(self, monkeypatch, temp_dir):
        monkeypatch.setattr(logger_module, "LOG_DIR", temp_dir)
        logger_module.set_logger("main.log")
        logger_module.logger.info("hello")
        _flush_handlers()

        extra_path = os.path.join(temp_dir, "extra.log")
        with open(extra_path, "w", encoding="utf-8") as handle:
            handle.write("data")

        deleted = logger_module.clear_logs(temp_dir)

        assert sorted(os.path.basename(path) for path in deleted) == ["extra.log", "main.log"]
        assert os.listdir(temp_dir) == []
        assert [
            handler for handler in logger_module.logger.handlers
            if isinstance(handler, logging.FileHandler)
        ] == []

    def test_clear_logs_preserves_non_log_files(self, temp_dir):
        with open(os.path.join(temp_dir, "notes.txt"), "w", encoding="utf-8") as handle:
            handle.write("keep me")
        with open(os.path.join(temp_dir, "main.log"), "w", encoding="utf-8") as handle:
            handle.write("delete me")

        deleted = logger_module.clear_logs(temp_dir)

        assert sorted(os.path.basename(path) for path in deleted) == ["main.log"]
        assert os.path.exists(os.path.join(temp_dir, "notes.txt"))
