import os

from typer.testing import CliRunner

from app.definitions import build_workspace_paths
from cli.main import app


class TestCliLogs:
    def test_clear_logs_command_removes_files(self, temp_dir):
        logs_dir = build_workspace_paths(temp_dir).log_dir
        os.makedirs(logs_dir, exist_ok=True)
        with open(os.path.join(logs_dir, "main.log"), "w", encoding="utf-8") as handle:
            handle.write("hello")
        with open(os.path.join(logs_dir, "main.log.1"), "w", encoding="utf-8") as handle:
            handle.write("backup")

        result = CliRunner().invoke(app, ["clear-logs", "--force", "--workspace", temp_dir])

        assert result.exit_code == 0
        assert os.listdir(logs_dir) == []
        assert "Log cleanup complete." in result.stdout

    def test_clear_logs_command_reports_when_empty(self, temp_dir):
        logs_dir = build_workspace_paths(temp_dir).log_dir
        os.makedirs(logs_dir, exist_ok=True)

        result = CliRunner().invoke(app, ["clear-logs", "--force", "--workspace", temp_dir])

        assert result.exit_code == 0
        assert "No log files to delete." in result.stdout

    def test_clear_logs_command_preserves_non_log_files(self, temp_dir):
        logs_dir = build_workspace_paths(temp_dir).log_dir
        os.makedirs(logs_dir, exist_ok=True)
        with open(os.path.join(logs_dir, "main.log"), "w", encoding="utf-8") as handle:
            handle.write("hello")
        with open(os.path.join(logs_dir, "notes.txt"), "w", encoding="utf-8") as handle:
            handle.write("keep")

        result = CliRunner().invoke(app, ["clear-logs", "--force", "--workspace", temp_dir])

        assert result.exit_code == 0
        assert os.listdir(logs_dir) == ["notes.txt"]
