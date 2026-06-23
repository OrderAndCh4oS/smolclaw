import os
from pathlib import Path

from typer.testing import CliRunner

from app.definitions import build_workspace_paths
from cli.main import app


def _seed_workspace(path: str):
    paths = build_workspace_paths(path)
    for directory in (
        paths.memory_docs_dir,
        paths.log_dir,
        paths.sessions_dir,
    ):
        os.makedirs(directory, exist_ok=True)
    Path(paths.memory_docs_dir, "mem-preference.md").write_text("memory")
    Path(paths.memory_docs_dir, "journal-session.md").write_text("journal")
    Path(paths.log_dir, "main.log").write_text("log")
    Path(paths.sqlite_db_path).write_text("db")
    Path(paths.sqlite_db_path + "-wal").write_text("wal")
    Path(paths.sqlite_db_path + "-shm").write_text("shm")
    Path(paths.kg_db_path).write_text("kg")
    Path(paths.sessions_dir, "default.jsonl").write_text("{}")
    return paths


class TestCliReset:
    def test_reset_logs_flag_clears_only_logs(self, temp_dir):
        paths = _seed_workspace(temp_dir)

        result = CliRunner().invoke(app, ["reset", "--force", "--logs", "--workspace", temp_dir])

        assert result.exit_code == 0
        assert os.listdir(paths.log_dir) == []
        assert Path(paths.memory_docs_dir, "mem-preference.md").exists()
        assert Path(paths.kg_db_path).exists()
        assert Path(paths.sqlite_db_path).exists()

    def test_reset_journals_flag_preserves_other_memory_docs(self, temp_dir):
        paths = _seed_workspace(temp_dir)

        result = CliRunner().invoke(app, ["reset", "--force", "--journals", "--workspace", temp_dir])

        assert result.exit_code == 0
        assert not Path(paths.memory_docs_dir, "journal-session.md").exists()
        assert Path(paths.memory_docs_dir, "mem-preference.md").exists()
        assert Path(paths.sqlite_db_path).exists()

    def test_reset_rag_and_kg_flags_preserve_sessions_and_memory_docs(self, temp_dir):
        paths = _seed_workspace(temp_dir)

        result = CliRunner().invoke(
            app,
            ["reset", "--force", "--rag", "--kg", "--workspace", temp_dir],
        )

        assert result.exit_code == 0
        assert Path(paths.sqlite_db_path).exists()
        assert not Path(paths.sqlite_db_path + "-wal").exists()
        assert not Path(paths.sqlite_db_path + "-shm").exists()
        assert Path(paths.kg_db_path).exists()
        assert "graphml" in Path(paths.kg_db_path).read_text()
        assert Path(paths.sessions_dir, "default.jsonl").exists()
        assert Path(paths.memory_docs_dir, "mem-preference.md").exists()

    def test_reset_without_component_flags_keeps_full_reset_behavior(self, temp_dir):
        paths = _seed_workspace(temp_dir)

        result = CliRunner().invoke(app, ["reset", "--force", "--workspace", temp_dir])

        assert result.exit_code == 0
        assert Path(paths.sqlite_db_path).exists()
        assert Path(paths.kg_db_path).exists()
        assert "graphml" in Path(paths.kg_db_path).read_text()
        assert os.listdir(paths.memory_docs_dir) == []
        assert os.listdir(paths.sessions_dir) == []
