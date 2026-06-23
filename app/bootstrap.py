"""Project bootstrap helpers for repo-local agent guidance."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.workspace import WorkspaceContext


START_MARKER = "<!-- smolclaw:init:start -->"
END_MARKER = "<!-- smolclaw:init:end -->"


@dataclass(frozen=True)
class BootstrapResult:
    path: str
    created: bool
    updated: bool


def init_project_guidance(workspace: WorkspaceContext) -> BootstrapResult:
    path = workspace.resolve_path("AGENTS.md")
    block = _render_guidance_block(workspace)
    created = not os.path.exists(path)
    existing = ""
    if not created:
        with open(path, encoding="utf-8") as handle:
            existing = handle.read()
    updated_content = _replace_or_append_block(existing, block)
    updated = created or updated_content != existing
    if updated:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(updated_content)
    return BootstrapResult(path=path, created=created, updated=updated)


def _replace_or_append_block(existing: str, block: str) -> str:
    if START_MARKER in existing and END_MARKER in existing:
        before, rest = existing.split(START_MARKER, 1)
        _, after = rest.split(END_MARKER, 1)
        return before.rstrip() + "\n\n" + block + after
    if not existing.strip():
        return block
    return existing.rstrip() + "\n\n" + block


def _render_guidance_block(workspace: WorkspaceContext) -> str:
    project_name = os.path.basename(workspace.root_dir.rstrip(os.sep)) or "project"
    commands = _detected_commands(workspace)
    command_lines = "\n".join(f"- `{command}`" for command in commands)
    return "\n".join([
        START_MARKER,
        f"# SmolClaw Project Notes: {project_name}",
        "",
        "Use this repository as the source of truth. Inspect relevant files before editing, keep changes scoped, and verify mutations before marking work complete.",
        "",
        "Important local workflow:",
        "- Run `git status --short --branch` before making changes.",
        "- Read target files before editing existing files.",
        "- Prefer targeted tests that cover the changed behavior.",
        "- Do not read or modify `.env` or other secret files.",
        "",
        "Detected verification commands:",
        command_lines,
        END_MARKER,
        "",
    ])


def _detected_commands(workspace: WorkspaceContext) -> list[str]:
    root = workspace.root_dir
    commands: list[str] = []
    if os.path.exists(os.path.join(root, "pytest.ini")) or os.path.exists(os.path.join(root, "pyproject.toml")):
        commands.append("python -m pytest")
    if os.path.exists(os.path.join(root, "package.json")):
        commands.append("npm test")
    if os.path.exists(os.path.join(root, "Cargo.toml")):
        commands.append("cargo test")
    if os.path.exists(os.path.join(root, "go.mod")):
        commands.append("go test ./...")
    return commands or ["<add project-specific verification command>"]
