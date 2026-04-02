import os

import pytest

from app.agent_config import AgentConfig, AgentConfigLoader


class TestAgentConfig:
    def test_agent_config_required_fields(self):
        config = AgentConfig(
            name="researcher",
            model="gpt-5.2-instant",
            persona="You are a researcher.",
            tools=["web_search", "memory_search"],
        )
        assert config.name == "researcher"
        assert config.model == "gpt-5.2-instant"
        assert config.persona == "You are a researcher."
        assert config.tools == ["web_search", "memory_search"]

    def test_agent_config_defaults(self):
        config = AgentConfig(
            name="test",
            model="gpt-4.1-mini",
            persona="Test agent.",
            tools=[],
        )
        assert config.max_iterations == 15
        assert config.memory_window == 20
        assert config.bootstrap_path is None

    def test_agent_config_is_frozen(self):
        config = AgentConfig(
            name="test",
            model="gpt-4.1-mini",
            persona="Test agent.",
            tools=[],
        )
        with pytest.raises(AttributeError):
            config.name = "changed"


class TestAgentConfigLoader:
    def test_load_single_agent(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agents.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: researcher\n"
                "    model: gpt-5.2-instant\n"
                "    persona: You are a researcher.\n"
                "    tools:\n"
                "      - web_search\n"
            )
        configs = AgentConfigLoader.load(yaml_path)
        assert len(configs) == 1
        assert "researcher" in configs
        assert configs["researcher"].model == "gpt-5.2-instant"

    def test_load_multiple_agents(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agents.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: researcher\n"
                "    model: gpt-5.2-instant\n"
                "    persona: Researcher agent.\n"
                "    tools: [web_search]\n"
                "  - name: writer\n"
                "    model: gpt-5.2-pro\n"
                "    persona: Writer agent.\n"
                "    tools: [write_file]\n"
            )
        configs = AgentConfigLoader.load(yaml_path)
        assert len(configs) == 2
        assert "researcher" in configs
        assert "writer" in configs

    def test_load_with_defaults(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agents.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: minimal\n"
                "    model: gpt-4.1-mini\n"
                "    persona: Minimal agent.\n"
            )
        configs = AgentConfigLoader.load(yaml_path)
        config = configs["minimal"]
        assert config.tools == []
        assert config.max_iterations == 15
        assert config.memory_window == 20
        assert config.bootstrap_path is None

    def test_load_with_all_fields(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agents.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: custom\n"
                "    model: gpt-5.2-pro\n"
                "    persona: Custom agent.\n"
                "    tools: [web_search, memory_store]\n"
                "    bootstrap_path: /tmp/AGENT.md\n"
                "    max_iterations: 25\n"
                "    memory_window: 40\n"
            )
        configs = AgentConfigLoader.load(yaml_path)
        config = configs["custom"]
        assert config.bootstrap_path == "/tmp/AGENT.md"
        assert config.max_iterations == 25
        assert config.memory_window == 40
        assert config.tools == ["web_search", "memory_store"]

    def test_load_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            AgentConfigLoader.load("/nonexistent/agents.yaml")


class TestAgentConfigSkills:
    def test_skills_default_empty(self):
        config = AgentConfig(name="test", model="m", persona="p", tools=[])
        assert config.skills == []

    def test_load_with_skills(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agents.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: skilled\n"
                "    model: gpt-5.4-mini\n"
                "    persona: Skilled agent.\n"
                "    skills:\n"
                "      - memory-hygiene.md\n"
                "      - code-review.md\n"
            )
        configs = AgentConfigLoader.load(yaml_path)
        assert configs["skilled"].skills == ["memory-hygiene.md", "code-review.md"]

    def test_load_without_skills_gets_empty(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agents.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: plain\n"
                "    model: m\n"
                "    persona: p\n"
            )
        configs = AgentConfigLoader.load(yaml_path)
        assert configs["plain"].skills == []


class TestAgentConfigPermissionMode:
    def test_permission_mode_default_full(self):
        config = AgentConfig(name="test", model="m", persona="p", tools=[])
        assert config.permission_mode == "full"

    def test_load_with_permission_mode(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agents.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: reader\n"
                "    model: m\n"
                "    persona: p\n"
                "    permission_mode: plan\n"
            )
        configs = AgentConfigLoader.load(yaml_path)
        assert configs["reader"].permission_mode == "plan"

    def test_load_without_permission_mode_gets_full(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agents.yaml")
        with open(yaml_path, "w") as f:
            f.write(
                "agents:\n"
                "  - name: agent\n"
                "    model: m\n"
                "    persona: p\n"
            )
        configs = AgentConfigLoader.load(yaml_path)
        assert configs["agent"].permission_mode == "full"


class TestRepoAgentsConfig:
    def test_repo_agents_use_explicit_modules_and_permission_modes(self):
        yaml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.yaml")
        configs = AgentConfigLoader.load(yaml_path)

        assert configs["default"].modules == ["transport.direct", "memory"]
        assert configs["default"].permission_mode == "plan"
        assert "write_file" not in configs["default"].tools
        assert "edit_file" not in configs["default"].tools
        assert "exec" not in configs["default"].tools

        assert configs["researcher"].modules == ["transport.direct", "memory"]
        assert configs["researcher"].permission_mode == "research"
        assert "memory_store" in configs["researcher"].tools
        assert "exec" not in configs["researcher"].tools

        assert configs["coder"].modules == ["transport.direct", "memory"]
        assert configs["coder"].permission_mode == "execute"
        assert "exec" in configs["coder"].tools
        assert "write_file" in configs["coder"].tools

        assert configs["orchestrator"].modules == ["memory", "orchestration", "subagents"]
        assert configs["orchestrator"].permission_mode == "delegate_only"
        assert "transport.direct" not in configs["orchestrator"].modules
        assert "write_file" not in configs["orchestrator"].tools
        assert "exec" not in configs["orchestrator"].tools
