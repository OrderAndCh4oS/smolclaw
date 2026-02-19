from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass(frozen=True)
class AgentConfig:
    name: str
    model: str
    persona: str
    tools: List[str] = field(default_factory=list)
    bootstrap_path: Optional[str] = None
    max_iterations: int = 15
    memory_window: int = 20


class AgentConfigLoader:
    @staticmethod
    def load(path: str) -> Dict[str, AgentConfig]:
        with open(path) as f:
            raw = yaml.safe_load(f)
        agents = {}
        for entry in raw["agents"]:
            config = AgentConfig(
                name=entry["name"],
                model=entry["model"],
                persona=entry["persona"],
                tools=entry.get("tools", []),
                bootstrap_path=entry.get("bootstrap_path"),
                max_iterations=entry.get("max_iterations", 15),
                memory_window=entry.get("memory_window", 20),
            )
            agents[config.name] = config
        return agents
