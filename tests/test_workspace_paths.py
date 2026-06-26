import os

from app.definitions import build_workspace_paths, ensure_workspace_dirs


class TestWorkspacePaths:
    def test_build_workspace_paths_uses_workspace_root_layout(self, temp_dir):
        workspace_root = os.path.join(temp_dir, "topic-a")

        paths = build_workspace_paths(workspace_root)

        assert paths.root_dir == os.path.abspath(workspace_root)
        assert paths.state_root_dir == os.path.join(os.path.abspath(workspace_root), ".smolclaw")
        assert paths.data_dir == os.path.join(paths.state_root_dir, "stores")
        assert paths.memory_docs_dir == os.path.join(paths.state_root_dir, "memory")
        assert paths.research_dir == os.path.join(paths.state_root_dir, "research")
        assert paths.work_loop_dir == os.path.join(paths.state_root_dir, "work-loop")
        assert paths.input_docs_dir == paths.research_dir
        assert paths.sessions_dir == os.path.join(paths.state_root_dir, "stores", "sessions")
        assert paths.approvals_dir == os.path.join(paths.state_root_dir, "stores", "approvals")
        assert paths.prompt_history_path == os.path.join(paths.sessions_dir, "prompt_history.txt")

    def test_build_workspace_paths_can_split_source_and_state_roots(self, temp_dir):
        source_root = os.path.join(temp_dir, "source")
        state_root = os.path.join(temp_dir, "state")

        paths = build_workspace_paths(source_root, state_root=state_root)

        assert paths.root_dir == os.path.abspath(source_root)
        assert paths.state_root_dir == os.path.abspath(state_root)
        assert paths.data_dir == os.path.join(paths.state_root_dir, "stores")
        assert paths.sessions_dir == os.path.join(paths.state_root_dir, "stores", "sessions")
        assert paths.approvals_dir == os.path.join(paths.state_root_dir, "stores", "approvals")
        assert paths.memory_docs_dir == os.path.join(paths.state_root_dir, "memory")
        assert paths.research_dir == os.path.join(paths.state_root_dir, "research")
        assert paths.work_loop_dir == os.path.join(paths.state_root_dir, "work-loop")

    def test_ensure_workspace_dirs_creates_isolated_layout(self, temp_dir):
        workspace_root = os.path.join(temp_dir, "topic-b")

        paths = ensure_workspace_dirs(build_workspace_paths(workspace_root))

        for dir_path in (
            paths.root_dir,
            paths.state_root_dir,
            paths.data_dir,
            paths.sessions_dir,
            paths.approvals_dir,
            paths.memory_docs_dir,
            paths.log_dir,
            paths.cache_dir,
            paths.work_loop_dir,
            paths.research_dir,
        ):
            assert os.path.isdir(dir_path)
