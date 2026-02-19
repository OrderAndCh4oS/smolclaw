import os

import pytest

from app.context_builder import ContextBuilder


class TestContextBuilder:
    def test_build_system_prompt_includes_identity(self, temp_dir):
        builder = ContextBuilder(bootstrap_path=os.path.join(temp_dir, "AGENT.md"))
        prompt = builder.build_system_prompt()
        assert "SmolClaw" in prompt

    def test_build_system_prompt_includes_bootstrap(self, temp_dir):
        agent_md = os.path.join(temp_dir, "AGENT.md")
        with open(agent_md, "w") as f:
            f.write("Custom agent instructions here.")
        builder = ContextBuilder(bootstrap_path=agent_md)
        prompt = builder.build_system_prompt()
        assert "Custom agent instructions here." in prompt

    def test_build_system_prompt_missing_bootstrap(self, temp_dir):
        builder = ContextBuilder(bootstrap_path=os.path.join(temp_dir, "nonexistent.md"))
        prompt = builder.build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_build_messages_structure(self, temp_dir):
        builder = ContextBuilder(bootstrap_path=os.path.join(temp_dir, "AGENT.md"))
        history = [
            {"role": "user", "content": "old message"},
            {"role": "assistant", "content": "old reply"},
        ]
        messages = builder.build_messages(history=history, user_content="new question")
        assert messages[0]["role"] == "system"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "new question"
        assert len(messages) == 4  # system + 2 history + user

    def test_build_messages_empty_history(self, temp_dir):
        builder = ContextBuilder(bootstrap_path=os.path.join(temp_dir, "AGENT.md"))
        messages = builder.build_messages(history=[], user_content="hello")
        assert len(messages) == 2  # system + user
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_build_messages_with_history(self, temp_dir):
        builder = ContextBuilder(bootstrap_path=os.path.join(temp_dir, "AGENT.md"))
        history = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        messages = builder.build_messages(history=history, user_content="q3")
        # system + 4 history + user
        assert len(messages) == 6
        assert messages[1]["content"] == "q1"
        assert messages[4]["content"] == "a2"
        assert messages[5]["content"] == "q3"


class TestContextBuilderPersona:
    def test_build_system_prompt_with_persona(self):
        builder = ContextBuilder(persona="You are Researcher, a fast-thinking research agent.")
        prompt = builder.build_system_prompt()
        assert "Researcher" in prompt
        assert "SmolClaw" not in prompt

    def test_build_system_prompt_without_persona_unchanged(self):
        builder = ContextBuilder()
        prompt = builder.build_system_prompt()
        assert "SmolClaw" in prompt

    def test_build_system_prompt_persona_with_bootstrap(self, temp_dir):
        agent_md = os.path.join(temp_dir, "AGENT.md")
        with open(agent_md, "w") as f:
            f.write("Custom bootstrap instructions.")
        builder = ContextBuilder(bootstrap_path=agent_md, persona="You are Writer.")
        prompt = builder.build_system_prompt()
        assert "Writer" in prompt
        assert "Custom bootstrap instructions." in prompt
        assert "SmolClaw" not in prompt


class TestContextBuilderSharedBootstrap:
    def test_shared_bootstrap_included(self, temp_dir):
        shared = os.path.join(temp_dir, "AGENT.md")
        with open(shared, "w") as f:
            f.write("Shared docs reference.")
        builder = ContextBuilder(shared_bootstrap_path=shared)
        prompt = builder.build_system_prompt()
        assert "Shared docs reference." in prompt
        assert "Shared Bootstrap" in prompt

    def test_shared_and_agent_bootstrap_both_included(self, temp_dir):
        shared = os.path.join(temp_dir, "AGENT.md")
        agent = os.path.join(temp_dir, "writer.md")
        with open(shared, "w") as f:
            f.write("Shared docs reference.")
        with open(agent, "w") as f:
            f.write("Writer-specific instructions.")
        builder = ContextBuilder(
            shared_bootstrap_path=shared, bootstrap_path=agent, persona="You are Writer.",
        )
        prompt = builder.build_system_prompt()
        assert "Shared docs reference." in prompt
        assert "Writer-specific instructions." in prompt
        assert "Shared Bootstrap" in prompt
        assert "Agent Bootstrap" in prompt

    def test_shared_and_agent_same_file_no_duplication(self, temp_dir):
        shared = os.path.join(temp_dir, "AGENT.md")
        with open(shared, "w") as f:
            f.write("Shared docs reference.")
        builder = ContextBuilder(shared_bootstrap_path=shared, bootstrap_path=shared)
        prompt = builder.build_system_prompt()
        assert prompt.count("Shared docs reference.") == 1

    def test_shared_bootstrap_missing_file(self, temp_dir):
        builder = ContextBuilder(shared_bootstrap_path=os.path.join(temp_dir, "missing.md"))
        prompt = builder.build_system_prompt()
        assert "SmolClaw" in prompt
        assert "Shared Bootstrap" not in prompt

    def test_shared_bootstrap_with_persona(self, temp_dir):
        shared = os.path.join(temp_dir, "AGENT.md")
        with open(shared, "w") as f:
            f.write("Shared context here.")
        builder = ContextBuilder(shared_bootstrap_path=shared, persona="You are Researcher.")
        prompt = builder.build_system_prompt()
        assert "Researcher" in prompt
        assert "Shared context here." in prompt
        assert "SmolClaw" not in prompt
