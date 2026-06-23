import os
from dataclasses import dataclass

from app.definitions import WorkspacePaths, build_workspace_paths, ensure_workspace_dirs


@dataclass(frozen=True)
class WorkspaceContext:
    paths: WorkspacePaths

    @classmethod
    def from_root(
        cls,
        workspace_root: str | None = None,
        *,
        state_root: str | None = None,
    ) -> "WorkspaceContext":
        return cls(build_workspace_paths(workspace_root, state_root=state_root))

    @property
    def root_dir(self) -> str:
        return os.path.realpath(self.paths.root_dir)

    @property
    def state_root_dir(self) -> str:
        return os.path.realpath(self.paths.state_root_dir)

    def ensure_dirs(self) -> "WorkspaceContext":
        ensure_workspace_dirs(self.paths)
        return self

    def resolve_path(self, path: str | None = None, *, default_to_root: bool = True) -> str:
        if path in (None, ""):
            candidate = self.root_dir if default_to_root else ""
        else:
            expanded = os.path.expanduser(path)
            candidate = expanded if os.path.isabs(expanded) else os.path.join(self.root_dir, expanded)
        return os.path.realpath(candidate)

    def contains(self, path: str) -> bool:
        real = os.path.realpath(path)
        return real == self.root_dir or real.startswith(self.root_dir + os.sep)

    def resolve_contained_path(
        self,
        path: str | None = None,
        *,
        default_to_root: bool = True,
        label: str = "path",
    ) -> tuple[str | None, str | None]:
        resolved = self.resolve_path(path, default_to_root=default_to_root)
        if not self.contains(resolved):
            return None, f"Error: {label} '{path}' is outside workspace"
        return resolved, None
