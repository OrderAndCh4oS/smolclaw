import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent_config import AgentConfig
from app.agent_factory import ChildAgentFactory, build_agent_loop as _build_agent_loop
from app.agent_loop import AgentLoop
from app.model_settings import RuntimeModelSettings
from app.session import SessionManager
from app.tools.base import Tool
from app.tools.factory import build_tool_registry
from app.tools.registry import ToolRegistry
from app.tools.tool_search import ToolSearchTool
from app.tools.safety import ExplorationEvidence
from app.workspace import WorkspaceContext


class StubToolA(Tool):
    @property
    def name(self) -> str:
        return "tool_a"

    @property
    def description(self) -> str:
        return "Tool A"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "a"


class StubToolB(Tool):
    @property
    def name(self) -> str:
        return "tool_b"

    @property
    def description(self) -> str:
        return "Tool B"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "b"


class StubToolC(Tool):
    @property
    def name(self) -> str:
        return "tool_c"

    @property
    def description(self) -> str:
        return "Tool C"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> str:
        return "c"


class DeferredHiddenTool(Tool):
    @property
    def name(self) -> str:
        return "hidden_tool"

    @property
    def description(self) -> str:
        return "A hidden runtime tool"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }

    @property
    def deferred(self) -> bool:
        return True

    async def execute(self, **kwargs) -> str:
        return f"hidden:{kwargs['value']}"


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo input"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, **kwargs) -> str:
        return kwargs["text"]


class CaptureChildFactoryTool(Tool):
    def __init__(self, child_agent_factory=None):
        self.child_agent_factory = child_agent_factory

    @property
    def name(self) -> str:
        return "capture_child_factory"

    @property
    def description(self) -> str:
        return "Expose the bound child agent factory for tests."

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def bind(self, runtime_ctx) -> Tool:
        return CaptureChildFactoryTool(
            child_agent_factory=runtime_ctx.child_agent_factory,
        )

    async def execute(self, **kwargs) -> str:
        return "captured"


@pytest.fixture
def master_registry():
    registry = ToolRegistry()
    registry.register(StubToolA())
    registry.register(StubToolB())
    registry.register(StubToolC())
    return registry


@pytest.fixture
def researcher_config():
    return AgentConfig(
        name="researcher",
        model="gpt-5.2-instant",
        persona="You are Researcher.",
        tools=["tool_a", "tool_b"],
        max_iterations=20,
        memory_window=30,
    )


@pytest.fixture
def writer_config():
    return AgentConfig(
        name="writer",
        model="gpt-5.2-pro",
        persona="You are Writer.",
        tools=["tool_b", "tool_c"],
    )


def _mock_create_llm(completion_model=None, **kwargs):
    mock = MagicMock()
    mock.completion_model = completion_model
    mock.reasoning_effort = None
    return mock


def build_agent_loop(*args, **kwargs):
    kwargs.setdefault("llm_factory", _mock_create_llm)
    return _build_agent_loop(*args, **kwargs)


class TestAgentFactory:
    def test_build_agent_loop_returns_agent_loop(
        self, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert isinstance(loop, AgentLoop)

    def test_build_agent_loop_uses_config_model(
        self, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert loop.llm.completion_model == "gpt-5.2-instant"

    def test_build_agent_loop_uses_subagent_model_default_for_children(
        self, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        settings = RuntimeModelSettings()

        loop = build_agent_loop(
            researcher_config,
            master_registry,
            mock_smol_rag,
            sm,
            model_settings=settings,
            is_child_agent=True,
        )

        assert loop.llm.completion_model == "gpt-5.5"
        assert loop.llm.reasoning_effort == "medium"

    def test_build_agent_loop_filters_tools(
        self, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        defs = loop.tool_registry.get_definitions()
        names = sorted([d["function"]["name"] for d in defs])
        assert names == ["tool_a", "tool_b"]

    @pytest.mark.asyncio
    async def test_build_agent_loop_checkpoints_filesystem_mutations(
        self, mock_smol_rag, sessions_dir, temp_dir
    ):
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        master = build_tool_registry(
            smol_rag=None,
            workspace=workspace,
            capability_names=["filesystem"],
        )
        config = AgentConfig(
            name="coder",
            model="gpt-5.5",
            persona="You write code.",
            tools=["write_file"],
        )
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(config, master, mock_smol_rag, sm, workspace=workspace)
        loop.safety_state.did_git_status = True
        loop.safety_state.did_search = True
        loop.safety_state.evidence.append(ExplorationEvidence(kind="search", path=workspace.root_dir))

        result = await loop.tool_registry.execute(
            "write_file",
            {"path": "created.txt", "content": "checkpoint me"},
        )

        assert "Written" in result
        checkpoints_dir = workspace.paths.checkpoints_dir
        checkpoint_files = [name for name in os.listdir(checkpoints_dir) if name.endswith(".json")]
        assert len(checkpoint_files) == 1

    @pytest.mark.asyncio
    async def test_build_agent_loop_loads_workspace_permission_policy(
        self, mock_smol_rag, sessions_dir, temp_dir, monkeypatch
    ):
        monkeypatch.setenv("HOME", os.path.join(temp_dir, "home"))
        monkeypatch.delenv("SMOLCLAW_PERMISSION_POLICY", raising=False)
        workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
        policy_dir = os.path.join(temp_dir, ".smolclaw")
        os.makedirs(policy_dir, exist_ok=True)
        with open(os.path.join(policy_dir, "permissions.yaml"), "w", encoding="utf-8") as handle:
            handle.write(
                "rules:\n"
                "  - subject: tool\n"
                "    pattern: tool_a\n"
                "    action: deny\n"
                "    reason: workspace policy blocks this tool\n"
            )
        master = ToolRegistry()
        master.register(StubToolA())
        config = AgentConfig(
            name="coder",
            model="gpt-5.5",
            persona="You write code.",
            tools=["tool_a"],
        )
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(config, master, mock_smol_rag, sm, workspace=workspace)

        result = await loop.tool_registry.execute("tool_a", {})

        assert result.startswith("Error: tool 'tool_a' denied by permission policy")
        assert "workspace policy blocks this tool" in result

    def test_build_agent_loop_uses_persona(
        self, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert loop.context_builder.persona == "You are Researcher."

    def test_build_agent_loop_session_key_isolation(
        self, researcher_config, writer_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop_r = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        loop_w = build_agent_loop(writer_config, master_registry, mock_smol_rag, sm)
        assert loop_r.session.key != loop_w.session.key
        assert "researcher" in loop_r.session.key
        assert "writer" in loop_w.session.key

    def test_build_agent_loop_shared_smol_rag(
        self, researcher_config, writer_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop_r = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        loop_w = build_agent_loop(writer_config, master_registry, mock_smol_rag, sm)
        assert loop_r.smol_rag is loop_w.smol_rag

    def test_build_agent_loop_uses_exact_session_key_when_provided(
        self, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(
            researcher_config,
            master_registry,
            mock_smol_rag,
            sm,
            session_key="plain-session",
        )
        assert loop.session.key == "plain-session"

    @pytest.mark.asyncio
    async def test_build_agent_loop_refreshes_tool_definitions_after_tool_search(
        self, mock_smol_rag, sessions_dir
    ):
        llm = MagicMock()
        seen_tool_names = []

        async def fake_tool_completion(**kwargs):
            tool_names = [tool["function"]["name"] for tool in (kwargs.get("tools") or [])]
            seen_tool_names.append(sorted(tool_names))
            if len(seen_tool_names) == 1:
                return {
                    "content": None,
                    "tool_calls": [{
                        "id": "call-1",
                        "name": "tool_search",
                        "arguments": {"query": "hidden"},
                    }],
                    "has_tool_calls": True,
                }
            if len(seen_tool_names) == 2:
                return {
                    "content": None,
                    "tool_calls": [{
                        "id": "call-2",
                        "name": "hidden_tool",
                        "arguments": {"value": "ok"},
                    }],
                    "has_tool_calls": True,
                }
            return {
                "content": "done",
                "tool_calls": None,
                "has_tool_calls": False,
            }

        llm.get_tool_completion = AsyncMock(side_effect=fake_tool_completion)
        llm.completion_model = "gpt-test"

        registry = ToolRegistry()
        registry.register(DeferredHiddenTool())
        registry.register(ToolSearchTool(registry))
        config = AgentConfig(
            name="researcher",
            model="gpt-test",
            persona="You are Researcher.",
            tools=["tool_search"],
        )

        loop = build_agent_loop(
            config,
            registry,
            mock_smol_rag,
            SessionManager(sessions_dir),
            llm_factory=lambda **_kwargs: llm,
        )
        result = await loop.process("find the hidden tool")

        assert result == "done"
        assert seen_tool_names[0] == ["tool_search"]
        assert seen_tool_names[1] == ["hidden_tool", "tool_search"]

    def test_child_agent_factory_uses_registry_factory_for_child_config(
        self, master_registry, mock_smol_rag, sessions_dir
    ):
        child_registry = ToolRegistry()
        child_registry.register(StubToolC())
        child_config = AgentConfig(
            name="writer",
            model="gpt-5.2-pro",
            persona="You are Writer.",
            tools=["tool_c"],
            capabilities=["child"],
        )
        factory = ChildAgentFactory(
            master_registry=master_registry,
            registry_factory=lambda config: child_registry if config.capabilities == ["child"] else master_registry,
            smol_rag=mock_smol_rag,
            workspace=None,
            session_manager=SessionManager(sessions_dir),
            parent_session_key="parent",
            llm_factory=_mock_create_llm,
        )

        loop = factory.build(child_config, purpose="spawn")

        defs = loop.tool_registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert names == ["tool_c"]

    def test_child_agent_factory_forwards_registry_factory_to_grandchildren(
        self, mock_smol_rag, sessions_dir
    ):
        root_registry = ToolRegistry()
        root_registry.register(CaptureChildFactoryTool())
        root_registry.register(StubToolA())

        child_registry = ToolRegistry()
        child_registry.register(CaptureChildFactoryTool())
        child_registry.register(StubToolB())

        grandchild_registry = ToolRegistry()
        grandchild_registry.register(CaptureChildFactoryTool())
        grandchild_registry.register(StubToolC())

        def registry_factory(config: AgentConfig) -> ToolRegistry:
            if config.capabilities == ["child"]:
                return child_registry
            if config.capabilities == ["child", "memory"]:
                return grandchild_registry
            return root_registry

        factory = ChildAgentFactory(
            master_registry=root_registry,
            registry_factory=registry_factory,
            smol_rag=mock_smol_rag,
            workspace=None,
            session_manager=SessionManager(sessions_dir),
            parent_session_key="parent",
            llm_factory=_mock_create_llm,
        )

        child_loop = factory.build(
            AgentConfig(
                name="writer",
                model="gpt-5.2-pro",
                persona="You are Writer.",
                tools=["capture_child_factory", "tool_b"],
                capabilities=["child"],
            ),
            purpose="spawn",
        )

        capture_tool = child_loop.tool_registry._tools["capture_child_factory"]
        grandchild_loop = capture_tool.child_agent_factory.build(
            AgentConfig(
                name="researcher",
                model="gpt-5.2-pro",
                persona="You are Researcher.",
                tools=["tool_c"],
                capabilities=["child", "memory"],
            ),
            purpose="spawn",
        )

        defs = grandchild_loop.tool_registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert names == ["tool_c"]

    def test_build_agent_loop_auto_exposes_tool_search_for_hidden_deferred_tools(
        self, mock_smol_rag, sessions_dir, temp_dir
    ):
        registry = build_tool_registry(
            smol_rag=mock_smol_rag,
            workspace=WorkspaceContext.from_root(temp_dir),
            llm=None,
            transport="direct",
        )
        config = AgentConfig(
            name="researcher",
            model="gpt-test",
            persona="You are Researcher.",
            tools=["memory_search"],
        )

        loop = build_agent_loop(
            config,
            registry,
            mock_smol_rag,
            SessionManager(sessions_dir),
        )

        defs = loop.tool_registry.get_definitions()
        names = sorted(d["function"]["name"] for d in defs)
        assert "memory_get" not in names
        assert "memory_search" in names
        assert "tool_search" in names

    def test_build_tool_registry_registers_tool_search_independent_of_capability_order(
        self, mock_smol_rag, temp_dir
    ):
        registry = build_tool_registry(
            smol_rag=mock_smol_rag,
            workspace=WorkspaceContext.from_root(temp_dir),
            llm=None,
            transport="direct",
            capability_names=["memory", "filesystem"],
        )

        defs = registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "tool_search" in names

    def test_build_tool_registry_registers_tool_search_for_explicit_capability_lists(
        self, mock_smol_rag, temp_dir
    ):
        registry = build_tool_registry(
            smol_rag=mock_smol_rag,
            workspace=WorkspaceContext.from_root(temp_dir),
            llm=None,
            transport="direct",
            capability_names=["filesystem", "memory"],
        )

        defs = registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "tool_search" in names

    @pytest.mark.asyncio
    async def test_build_agent_loop_installs_tool_hooks_on_standard_builder(
        self, mock_smol_rag, sessions_dir
    ):
        from app.hooks import HookRunner, ON_AFTER_TOOL, ON_BEFORE_TOOL

        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "name": "echo",
                    "arguments": {"text": "hello"},
                }],
                "has_tool_calls": True,
            },
            {
                "content": "done",
                "tool_calls": None,
                "has_tool_calls": False,
            },
        ])
        llm.completion_model = "gpt-test"

        registry = ToolRegistry()
        registry.register(EchoTool())
        config = AgentConfig(
            name="researcher",
            model="gpt-test",
            persona="You are Researcher.",
            tools=["echo"],
        )
        runner = HookRunner()
        events = []
        runner.on(ON_BEFORE_TOOL, lambda ctx: events.append(("before", ctx["tool_name"])))
        runner.on(ON_AFTER_TOOL, lambda ctx: events.append(("after", ctx["tool_name"])))

        loop = build_agent_loop(
            config,
            registry,
            mock_smol_rag,
            SessionManager(sessions_dir),
            hook_runner=runner,
            llm_factory=lambda **_kwargs: llm,
        )
        result = await loop.process("echo hello")

        assert result == "done"
        assert events == [("before", "echo"), ("after", "echo")]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "arguments"),
        [
            ("memory_search", {"query": "pricing"}),
            ("memory_recall", {"query": "pricing", "mode": "topic"}),
        ],
    )
    async def test_build_agent_loop_promotes_accessed_memory_via_tool_hooks(
        self, tool_name, arguments, mock_smol_rag, sessions_dir
    ):
        from app.tools.memory_tools import MemoryRecallTool, MemorySearchTool

        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "name": tool_name,
                    "arguments": arguments,
                }],
                "has_tool_calls": True,
            },
            {
                "content": "done",
                "tool_calls": None,
                "has_tool_calls": False,
            },
        ])
        llm.completion_model = "gpt-test"
        mock_smol_rag.mix_query = AsyncMock(return_value={
            "content": "results",
            "excerpt_ids": ["exc-1", "exc-2"],
        })

        registry = ToolRegistry()
        registry.register(MemorySearchTool(mock_smol_rag))
        registry.register(MemoryRecallTool(mock_smol_rag))
        config = AgentConfig(
            name="researcher",
            model="gpt-test",
            persona="You are Researcher.",
            tools=["memory_search", "memory_recall"],
        )

        mock_promote = AsyncMock()
        loop = build_agent_loop(
            config,
            registry,
            mock_smol_rag,
            SessionManager(sessions_dir),
            llm_factory=lambda **_kwargs: llm,
            promote_accessed_excerpts=mock_promote,
        )
        result = await loop.process("use memory")

        assert result == "done"
        mock_promote.assert_awaited_once_with(mock_smol_rag, ["exc-1", "exc-2"])

    @pytest.mark.asyncio
    async def test_build_agent_loop_promotes_temporal_recall_via_tool_hooks(
        self, mock_smol_rag, sessions_dir
    ):
        from app.tools.memory_tools import MemoryRecallTool

        llm = MagicMock()
        llm.get_tool_completion = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "name": "memory_recall",
                    "arguments": {"query": "recent work", "mode": "temporal", "days": 3},
                }],
                "has_tool_calls": True,
            },
            {
                "content": "done",
                "tool_calls": None,
                "has_tool_calls": False,
            },
        ])
        llm.completion_model = "gpt-test"
        mock_smol_rag.get_all_excerpts = AsyncMock(return_value={
            "exc-1": {
                "memory_type": "episode",
                "indexed_at": 9999999999,
                "excerpt": "did the work",
                "summary": "shipped",
            },
        })

        registry = ToolRegistry()
        registry.register(MemoryRecallTool(mock_smol_rag))
        config = AgentConfig(
            name="researcher",
            model="gpt-test",
            persona="You are Researcher.",
            tools=["memory_recall"],
        )

        mock_promote = AsyncMock()
        loop = build_agent_loop(
            config,
            registry,
            mock_smol_rag,
            SessionManager(sessions_dir),
            llm_factory=lambda **_kwargs: llm,
            promote_accessed_excerpts=mock_promote,
        )
        result = await loop.process("use memory")

        assert result == "done"
        mock_promote.assert_awaited_once_with(mock_smol_rag, ["exc-1"])

    @pytest.mark.asyncio
    async def test_memory_store_uses_runtime_bound_llm_for_auto_classification(
        self, mock_smol_rag, sessions_dir, temp_dir
    ):
        from app.taxonomy import MemoryType

        llm = MagicMock()
        llm.completion_model = "gpt-test"
        llm.get_tool_completion = AsyncMock(side_effect=[
            {
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "name": "memory_store",
                    "arguments": {"content": "store this"},
                }],
                "has_tool_calls": True,
            },
            {
                "content": "done",
                "tool_calls": None,
                "has_tool_calls": False,
            },
        ])

        from app.tools.memory_tools import MemoryStoreTool

        mock_classify = AsyncMock(return_value=(MemoryType.FACT, 0.9))
        registry = ToolRegistry()
        registry.register(MemoryStoreTool(
            mock_smol_rag,
            WorkspaceContext.from_root(temp_dir).ensure_dirs().paths.memory_docs_dir,
            classifier=mock_classify,
        ))
        config = AgentConfig(
            name="researcher",
            model="gpt-test",
            persona="You are Researcher.",
            tools=["memory_store"],
        )

        loop = build_agent_loop(
            config,
            registry,
            mock_smol_rag,
            SessionManager(sessions_dir),
            llm_factory=lambda **_kwargs: llm,
        )
        result = await loop.process("store this without a type")

        assert result == "done"
        mock_classify.assert_awaited_once()
        assert mock_classify.await_args.args[1] is llm

    def test_child_agent_factory_generates_unique_isolated_session_keys(
        self, master_registry, mock_smol_rag, sessions_dir
    ):
        factory = ChildAgentFactory(
            master_registry=master_registry,
            smol_rag=mock_smol_rag,
            workspace=None,
            session_manager=SessionManager(sessions_dir),
            parent_session_key="parent:session/unsafe",
        )

        first = factory.make_session_key("worker", "spawn-sub-1")
        second = factory.make_session_key("worker", "spawn-sub-1")

        assert first != second
        assert first.startswith("parent%3Asession%2Funsafe__worker__spawn_sub_1__")
        assert second.startswith("parent%3Asession%2Funsafe__worker__spawn_sub_1__")
        for ch in '<>:"/\\|?*':
            assert ch not in first
            assert ch not in second

    def test_child_agent_factory_resolves_memory_per_child_config(
        self, master_registry, mock_smol_rag, sessions_dir
    ):
        from app.hooks import ON_AFTER_TOOL

        async def _noop(_ctx):
            return None

        def resolve_smol_rag(config: AgentConfig):
            return mock_smol_rag if "memory" in config.capabilities else None

        def resolve_hook_runner_configurers(config: AgentConfig):
            if "memory" not in config.capabilities:
                return ()

            def _configure(hook_runner):
                hook_runner.on(ON_AFTER_TOOL, _noop)

            return (_configure,)

        factory = ChildAgentFactory(
            master_registry=master_registry,
            smol_rag=mock_smol_rag,
            workspace=None,
            session_manager=SessionManager(sessions_dir),
            parent_session_key="parent",
            smol_rag_resolver=resolve_smol_rag,
            hook_runner_configurers_resolver=resolve_hook_runner_configurers,
            llm_factory=_mock_create_llm,
        )

        memoryless = factory.build(
            AgentConfig(
                name="reader",
                model="gpt-test",
                persona="You are Reader.",
                tools=["tool_a"],
                capabilities=["filesystem"],
            ),
            purpose="spawn",
        )
        memory_enabled = factory.build(
            AgentConfig(
                name="researcher",
                model="gpt-test",
                persona="You are Researcher.",
                tools=["tool_a"],
                capabilities=["filesystem", "memory"],
            ),
            purpose="spawn",
        )

        assert memoryless.smol_rag is None
        assert ON_AFTER_TOOL not in memoryless.hook_runner.events
        assert memory_enabled.smol_rag is mock_smol_rag
        assert ON_AFTER_TOOL in memory_enabled.hook_runner.events
