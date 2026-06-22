import os

from app.context_builder import ContextBuilder
from app.runtime import _instruction_paths_for_workspace
from app.workspace import WorkspaceContext


def test_context_builder_loads_instruction_paths(temp_dir):
    instruction = os.path.join(temp_dir, "AGENTS.md")
    with open(instruction, "w") as f:
        f.write("Use focused tests.")

    builder = ContextBuilder(persona="Test agent", instruction_paths=[instruction])

    assert "Use focused tests." in builder.build_system_prompt()


def test_instruction_paths_prefer_agents_over_claude(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    with open(os.path.join(temp_dir, "AGENTS.md"), "w") as f:
        f.write("agents")
    with open(os.path.join(temp_dir, "CLAUDE.md"), "w") as f:
        f.write("claude")

    paths = _instruction_paths_for_workspace(workspace)

    assert os.path.realpath(os.path.join(temp_dir, "AGENTS.md")) in paths
    assert os.path.realpath(os.path.join(temp_dir, "CLAUDE.md")) not in paths


def test_instruction_paths_fallback_to_claude(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    with open(os.path.join(temp_dir, "CLAUDE.md"), "w") as f:
        f.write("claude")

    paths = _instruction_paths_for_workspace(workspace)

    assert os.path.realpath(os.path.join(temp_dir, "CLAUDE.md")) in paths
