import os
from datetime import datetime
from typing import Dict, List


class ContextBuilder:
    def __init__(self, bootstrap_path: str = None, persona: str = None):
        self.bootstrap_path = bootstrap_path
        self.persona = persona

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

        if self.bootstrap_path and os.path.exists(self.bootstrap_path):
            with open(self.bootstrap_path) as f:
                bootstrap = f.read().strip()
            if bootstrap:
                parts.append(f"\n--- Agent Bootstrap ---\n{bootstrap}")

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
