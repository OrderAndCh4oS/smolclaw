import os
from datetime import datetime
from typing import Dict, List, Optional


class ContextBuilder:
    def __init__(
        self,
        bootstrap_path: str = None,
        persona: str = None,
        shared_bootstrap_path: str = None,
        skills_paths: Optional[List[str]] = None,
        instruction_paths: Optional[List[str]] = None,
    ):
        self.bootstrap_path = bootstrap_path
        self.persona = persona
        self.shared_bootstrap_path = shared_bootstrap_path
        self.skills_paths = skills_paths or []
        self.instruction_paths = instruction_paths or []

    def _load_file(self, path: str) -> str | None:
        expanded = os.path.expanduser(path) if path else None
        if expanded and os.path.exists(expanded):
            with open(expanded) as f:
                content = f.read().strip()
            return content or None
        return None

    def build_system_prompt(self) -> str:
        if self.persona:
            parts = [
                self.persona,
                f"Current time: {datetime.now().isoformat()}",
            ]
        else:
            parts = [
                "You are SmolClaw, an agentic assistant with deep, persistent, associative memory.",
                f"Current time: {datetime.now().isoformat()}",
                "You have access to tools for file operations, shell commands, memory search, and knowledge graph queries.",
                "Use your memory tools to recall and store information across conversations.",
            ]

        shared = self._load_file(self.shared_bootstrap_path)
        agent = self._load_file(self.bootstrap_path)

        # Avoid duplicating content when shared and agent bootstrap are the same file
        if shared:
            parts.append(f"\n--- Shared Bootstrap ---\n{shared}")
        if agent and agent != shared:
            parts.append(f"\n--- Agent Bootstrap ---\n{agent}")

        for instruction_path in self.instruction_paths:
            content = self._load_file(instruction_path)
            if content:
                parts.append(f"\n--- Project Instructions: {instruction_path} ---\n{content}")

        # Inject preloaded skills as domain knowledge
        for skill_path in self.skills_paths:
            content = self._load_file(skill_path)
            if content:
                skill_name = os.path.splitext(os.path.basename(skill_path))[0]
                parts.append(f"\n--- Skill: {skill_name} ---\n{content}")

        return "\n".join(parts)

    def build_messages(
        self,
        history: List[Dict],
        user_content: str,
    ) -> List[Dict]:
        system_prompt = self.build_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})
        return messages

    async def build_messages_async(
        self,
        history: List[Dict],
        user_content: str,
    ) -> List[Dict]:
        return self.build_messages(history=history, user_content=user_content)
