import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_config import AgentConfig
from app.agent_factory import ChildAgentFactory, build_agent_loop
from app.agent_loop import AgentLoop
from app.session import SessionManager
from app.tools.base import Tool
from app.tools.factory import build_tool_registry
from app.tools.registry import ToolRegistry
from app.tools.tool_search import ToolSearchTool


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
    return mock


class TestAgentFactory:
    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_returns_agent_loop(
        self, _mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert isinstance(loop, AgentLoop)

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_uses_config_model(
        self, _mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert loop.llm.completion_model == "gpt-5.2-instant"

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_filters_tools(
        self, _mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        defs = loop.tool_registry.get_definitions()
        names = sorted([d["function"]["name"] for d in defs])
        assert names == ["tool_a", "tool_b"]

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_uses_persona(
        self, _mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        assert loop.context_builder.persona == "You are Researcher."

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_session_key_isolation(
        self, _mock_create, researcher_config, writer_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop_r = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        loop_w = build_agent_loop(writer_config, master_registry, mock_smol_rag, sm)
        assert loop_r.session.key != loop_w.session.key
        assert "researcher" in loop_r.session.key
        assert "writer" in loop_w.session.key

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_shared_smol_rag(
        self, _mock_create, researcher_config, writer_config, master_registry, mock_smol_rag, sessions_dir
    ):
        sm = SessionManager(sessions_dir)
        loop_r = build_agent_loop(researcher_config, master_registry, mock_smol_rag, sm)
        loop_w = build_agent_loop(writer_config, master_registry, mock_smol_rag, sm)
        assert loop_r.smol_rag is loop_w.smol_rag

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_uses_exact_session_key_when_provided(
        self, _mock_create, researcher_config, master_registry, mock_smol_rag, sessions_dir
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

        with patch("app.agent_factory.create_llm", return_value=llm):
            loop = build_agent_loop(
                config,
                registry,
                mock_smol_rag,
                SessionManager(sessions_dir),
            )
            result = await loop.process("find the hidden tool")

        assert result == "done"
        assert seen_tool_names[0] == ["tool_search"]
        assert seen_tool_names[1] == ["hidden_tool", "tool_search"]

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_child_agent_factory_uses_registry_factory_for_child_config(
        self, _mock_create, master_registry, mock_smol_rag, sessions_dir
    ):
        child_registry = ToolRegistry()
        child_registry.register(StubToolC())
        child_config = AgentConfig(
            name="writer",
            model="gpt-5.2-pro",
            persona="You are Writer.",
            tools=["tool_c"],
            modules=["child"],
        )
        factory = ChildAgentFactory(
            master_registry=master_registry,
            registry_factory=lambda config: child_registry if config.modules == ["child"] else master_registry,
            smol_rag=mock_smol_rag,
            session_manager=SessionManager(sessions_dir),
            parent_session_key="parent",
        )

        loop = factory.build(child_config, purpose="spawn")

        defs = loop.tool_registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert names == ["tool_c"]

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_child_agent_factory_forwards_registry_factory_to_grandchildren(
        self, _mock_create, mock_smol_rag, sessions_dir
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
            if config.modules == ["child"]:
                return child_registry
            if config.modules == ["child", "memory"]:
                return grandchild_registry
            return root_registry

        factory = ChildAgentFactory(
            master_registry=root_registry,
            registry_factory=registry_factory,
            smol_rag=mock_smol_rag,
            session_manager=SessionManager(sessions_dir),
            parent_session_key="parent",
        )

        child_loop = factory.build(
            AgentConfig(
                name="writer",
                model="gpt-5.2-pro",
                persona="You are Writer.",
                tools=["capture_child_factory", "tool_b"],
                modules=["child"],
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
                modules=["child", "memory"],
            ),
            purpose="spawn",
        )

        defs = grandchild_loop.tool_registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert names == ["tool_c"]

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_build_agent_loop_auto_exposes_tool_search_for_hidden_deferred_tools(
        self, _mock_create, mock_smol_rag, sessions_dir, temp_dir
    ):
        registry = build_tool_registry(
            smol_rag=mock_smol_rag,
            memory_docs_dir=temp_dir,
            workspace=temp_dir,
            llm=None,
            mode="direct",
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

    def test_build_tool_registry_registers_tool_search_independent_of_module_order(
        self, mock_smol_rag, temp_dir
    ):
        registry = build_tool_registry(
            smol_rag=mock_smol_rag,
            memory_docs_dir=temp_dir,
            workspace=temp_dir,
            llm=None,
            mode="direct",
            module_names=["tool_discovery", "memory", "transport.direct"],
        )

        defs = registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "tool_search" in names

    def test_build_tool_registry_registers_tool_search_for_explicit_module_lists(
        self, mock_smol_rag, temp_dir
    ):
        registry = build_tool_registry(
            smol_rag=mock_smol_rag,
            memory_docs_dir=temp_dir,
            workspace=temp_dir,
            llm=None,
            mode="direct",
            module_names=["transport.direct", "memory"],
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

        with patch("app.agent_factory.create_llm", return_value=llm):
            loop = build_agent_loop(
                config,
                registry,
                mock_smol_rag,
                SessionManager(sessions_dir),
                hook_runner=runner,
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

        with patch("app.agent_factory.create_llm", return_value=llm), \
            patch("app.agent_factory._promote_accessed_excerpts", new=AsyncMock()) as mock_promote:
            loop = build_agent_loop(
                config,
                registry,
                mock_smol_rag,
                SessionManager(sessions_dir),
            )
            result = await loop.process("use memory")

        assert result == "done"
        mock_promote.assert_awaited_once_with(mock_smol_rag, ["exc-1", "exc-2"])

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

        registry = build_tool_registry(
            smol_rag=mock_smol_rag,
            memory_docs_dir=temp_dir,
            workspace=temp_dir,
            llm=None,
            mode="direct",
        )
        config = AgentConfig(
            name="researcher",
            model="gpt-test",
            persona="You are Researcher.",
            tools=["memory_store"],
        )

        with patch("app.agent_factory.create_llm", return_value=llm), \
            patch("app.taxonomy.classify_chunk", new=AsyncMock(return_value=(MemoryType.FACT, 0.9))) as mock_classify:
            loop = build_agent_loop(
                config,
                registry,
                mock_smol_rag,
                SessionManager(sessions_dir),
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

    @patch("app.agent_factory.create_llm", side_effect=_mock_create_llm)
    def test_child_agent_factory_resolves_memory_per_child_config(
        self, _mock_create, master_registry, mock_smol_rag, sessions_dir
    ):
        from app.hooks import ON_AFTER_TOOL

        async def _noop(_ctx):
            return None

        def resolve_smol_rag(config: AgentConfig):
            return mock_smol_rag if "memory" in config.modules else None

        def resolve_hook_runner_configurers(config: AgentConfig):
            if "memory" not in config.modules:
                return ()

            def _configure(hook_runner):
                hook_runner.on(ON_AFTER_TOOL, _noop)

            return (_configure,)

        factory = ChildAgentFactory(
            master_registry=master_registry,
            smol_rag=mock_smol_rag,
            session_manager=SessionManager(sessions_dir),
            parent_session_key="parent",
            smol_rag_resolver=resolve_smol_rag,
            hook_runner_configurers_resolver=resolve_hook_runner_configurers,
        )

        memoryless = factory.build(
            AgentConfig(
                name="reader",
                model="gpt-test",
                persona="You are Reader.",
                tools=["tool_a"],
                modules=["transport.direct"],
            ),
            purpose="spawn",
        )
        memory_enabled = factory.build(
            AgentConfig(
                name="researcher",
                model="gpt-test",
                persona="You are Researcher.",
                tools=["tool_a"],
                modules=["transport.direct", "memory"],
            ),
            purpose="spawn",
        )

        assert memoryless.smol_rag is None
        assert ON_AFTER_TOOL not in memoryless.hook_runner.events
        assert memory_enabled.smol_rag is mock_smol_rag
        assert ON_AFTER_TOOL in memory_enabled.hook_runner.events
