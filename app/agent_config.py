from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

from app.runtime_capabilities import validate_capabilities


@dataclass(frozen=True)
class AgentConfig:
    name: str
    model: str
    persona: str
    tools: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    behaviors: List[str] = field(default_factory=list)
    bootstrap_path: Optional[str] = None
    max_iterations: int = 15
    memory_window: int = 20
    timeout: int = 600
    context_budget: int = 4000
    reflection: bool = False
    planning: bool = False
    skills: List[str] = field(default_factory=list)
    permission_mode: str = "full"


class AgentConfigLoader:
    @staticmethod
    def load(path: str) -> Dict[str, AgentConfig]:
        with open(path) as f:
            raw = yaml.safe_load(f)
        agents = {}
        for entry in raw["agents"]:
            if "modules" in entry:
                raise ValueError(
                    "Agent configs must use 'capabilities' instead of 'modules'. "
                    "Transport is now runtime-selected; remove legacy transport.* entries."
                )
            capabilities = entry.get("capabilities", [])
            validate_capabilities(capabilities)
            config = AgentConfig(
                name=entry["name"],
                model=entry["model"],
                persona=entry["persona"],
                tools=entry.get("tools", []),
                capabilities=capabilities,
                behaviors=entry.get("behaviors", []),
                bootstrap_path=entry.get("bootstrap_path"),
                max_iterations=entry.get("max_iterations", 15),
                memory_window=entry.get("memory_window", 20),
                timeout=entry.get("timeout", 600),
                context_budget=entry.get("context_budget", 4000),
                reflection=entry.get("reflection", False),
                planning=entry.get("planning", False),
                skills=entry.get("skills", []),
                permission_mode=entry.get("permission_mode", "full"),
            )
            agents[config.name] = config
        return agents
