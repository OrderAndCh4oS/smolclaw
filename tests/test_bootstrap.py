import os
import shutil

from typer.testing import CliRunner

from app.bootstrap import END_MARKER, START_MARKER, init_project_guidance
from app.workspace import WorkspaceContext
from cli.main import app


def test_init_project_guidance_creates_agents_file(temp_dir):
    with open(os.path.join(temp_dir, "pyproject.toml"), "w", encoding="utf-8") as handle:
        handle.write("[project]\nname = 'demo'\n")
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

    result = init_project_guidance(workspace)

    assert result.created is True
    assert result.updated is True
    with open(os.path.join(temp_dir, "AGENTS.md"), encoding="utf-8") as handle:
        content = handle.read()
    assert START_MARKER in content
    assert END_MARKER in content
    assert "python -m pytest" in content


def test_init_project_guidance_replaces_only_managed_block(temp_dir):
    path = os.path.join(temp_dir, "AGENTS.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "User notes stay.\n\n"
            f"{START_MARKER}\nold generated text\n{END_MARKER}\n\n"
            "More user notes.\n"
        )
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()

    result = init_project_guidance(workspace)

    assert result.created is False
    assert result.updated is True
    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    assert "User notes stay." in content
    assert "More user notes." in content
    assert "old generated text" not in content
    assert content.count(START_MARKER) == 1


def test_init_command_creates_agents_file(temp_dir):
    result = CliRunner().invoke(app, ["init", "--workspace", temp_dir])

    assert result.exit_code == 0
    assert "Created" in result.stdout
    assert os.path.exists(os.path.join(temp_dir, "AGENTS.md"))


def test_init_project_guidance_works_with_agent_eval_fixture(temp_dir):
    fixture_repo = os.path.join(
        os.path.dirname(__file__),
        "fixtures",
        "agent_tasks",
        "python_parser_bug",
        "repo",
    )
    workspace_root = os.path.join(temp_dir, "repo")
    shutil.copytree(fixture_repo, workspace_root)

    result = init_project_guidance(WorkspaceContext.from_root(workspace_root).ensure_dirs())

    assert result.created is True
    with open(os.path.join(workspace_root, "AGENTS.md"), encoding="utf-8") as handle:
        content = handle.read()
    assert "python -m pytest" in content
    assert "Do not read or modify `.env`" in content
