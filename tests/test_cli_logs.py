import os

from typer.testing import CliRunner

from cli.main import app


class TestCliLogs:
    def test_clear_logs_command_removes_files(self, temp_dir):
        logs_dir = os.path.join(temp_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        with open(os.path.join(logs_dir, "main.log"), "w", encoding="utf-8") as handle:
            handle.write("hello")
        with open(os.path.join(logs_dir, "main.log.1"), "w", encoding="utf-8") as handle:
            handle.write("backup")

        result = CliRunner().invoke(app, ["clear-logs", "--force", "--logs-dir", logs_dir])

        assert result.exit_code == 0
        assert os.listdir(logs_dir) == []
        assert "Log cleanup complete." in result.stdout

    def test_clear_logs_command_reports_when_empty(self, temp_dir):
        logs_dir = os.path.join(temp_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)

        result = CliRunner().invoke(app, ["clear-logs", "--force", "--logs-dir", logs_dir])

        assert result.exit_code == 0
        assert "No log files to delete." in result.stdout
