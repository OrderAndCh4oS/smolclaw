from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

import yaml

from app.model_defaults import (
    DEFAULT_AGENT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MEMORY_EXTRACT_MODEL,
    DEFAULT_MEMORY_QUERY_MODEL,
    DEFAULT_SUBAGENT_MODEL,
)
from app.workspace import WorkspaceContext


@dataclass(frozen=True)
class AdapterSelection:
    provider: str
    model: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, base: "AdapterSelection") -> "AdapterSelection":
        if not isinstance(data, Mapping):
            return base
        return cls(
            provider=str(data.get("provider") or base.provider),
            model=str(data["model"]) if data.get("model") else base.model,
        )

    def to_dict(self) -> dict:
        payload = {"provider": self.provider}
        if self.model:
            payload["model"] = self.model
        return payload


@dataclass(frozen=True)
class LlmAdapterConfig:
    default: AdapterSelection = field(default_factory=lambda: AdapterSelection("openai", DEFAULT_AGENT_MODEL))
    memory_extract: AdapterSelection = field(default_factory=lambda: AdapterSelection("openai", DEFAULT_MEMORY_EXTRACT_MODEL))
    memory_query: AdapterSelection = field(default_factory=lambda: AdapterSelection("openai", DEFAULT_MEMORY_QUERY_MODEL))
    embeddings: AdapterSelection = field(default_factory=lambda: AdapterSelection("openai", DEFAULT_EMBEDDING_MODEL))
    subagents: AdapterSelection = field(default_factory=lambda: AdapterSelection("openai", DEFAULT_SUBAGENT_MODEL))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, *, base: "LlmAdapterConfig | None" = None) -> "LlmAdapterConfig":
        baseline = base or cls()
        if not isinstance(data, Mapping):
            return baseline
        return cls(
            default=AdapterSelection.from_dict(data.get("default"), base=baseline.default),
            memory_extract=AdapterSelection.from_dict(data.get("memory_extract"), base=baseline.memory_extract),
            memory_query=AdapterSelection.from_dict(data.get("memory_query"), base=baseline.memory_query),
            embeddings=AdapterSelection.from_dict(data.get("embeddings"), base=baseline.embeddings),
            subagents=AdapterSelection.from_dict(data.get("subagents"), base=baseline.subagents),
        )


@dataclass(frozen=True)
class RuntimeAdapterConfig:
    llm: LlmAdapterConfig = field(default_factory=LlmAdapterConfig)
    task_source: AdapterSelection = field(default_factory=lambda: AdapterSelection("jira"))
    code_review: AdapterSelection = field(default_factory=lambda: AdapterSelection("github"))
    command: AdapterSelection = field(default_factory=lambda: AdapterSelection("subprocess"))

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any] | None,
        *,
        base: "RuntimeAdapterConfig | None" = None,
    ) -> "RuntimeAdapterConfig":
        baseline = base or cls()
        if not isinstance(data, Mapping):
            return baseline
        adapters = data.get("adapters") if isinstance(data.get("adapters"), Mapping) else data
        if not isinstance(adapters, Mapping):
            return baseline
        return cls(
            llm=LlmAdapterConfig.from_dict(adapters.get("llm"), base=baseline.llm),
            task_source=AdapterSelection.from_dict(_default_adapter_data(adapters.get("task_source")), base=baseline.task_source),
            code_review=AdapterSelection.from_dict(_default_adapter_data(adapters.get("code_review")), base=baseline.code_review),
            command=AdapterSelection.from_dict(_default_adapter_data(adapters.get("command")), base=baseline.command),
        )

    def with_overrides(
        self,
        *,
        default_model: str | None = None,
        subagent_model: str | None = None,
    ) -> "RuntimeAdapterConfig":
        llm = self.llm
        if default_model:
            llm = replace(llm, default=replace(llm.default, model=default_model))
        if subagent_model:
            llm = replace(llm, subagents=replace(llm.subagents, model=subagent_model))
        return replace(self, llm=llm)


def _default_adapter_data(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping) and isinstance(value.get("default"), Mapping):
        return value["default"]
    return value if isinstance(value, Mapping) else None


def runtime_config_paths(workspace: WorkspaceContext | None, *, include_user: bool = True) -> list[str]:
    paths: list[str] = []
    env_path = os.getenv("SMOLCLAW_CONFIG")
    if env_path:
        paths.append(_normalize_path(env_path))
    if include_user:
        paths.extend([
            _normalize_path("~/.config/smolclaw/config.yaml"),
            _normalize_path("~/.smolclaw/config.yaml"),
        ])
    if workspace is not None:
        paths.extend([
            os.path.join(workspace.state_root_dir, "config.yaml"),
            os.path.join(workspace.state_root_dir, "config.yml"),
            os.path.join(workspace.state_root_dir, "config.json"),
        ])
        roots = [workspace.state_root_dir]
        if workspace.root_dir != workspace.state_root_dir:
            roots.append(workspace.root_dir)
        for root in roots:
            paths.extend([
                os.path.join(root, ".smolclaw", "config.yaml"),
                os.path.join(root, ".smolclaw", "config.yml"),
                os.path.join(root, ".smolclaw", "config.json"),
            ])
    deduped = []
    seen = set()
    for path in paths:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        deduped.append(real)
    return deduped


def load_runtime_config(workspace: WorkspaceContext | None = None) -> RuntimeAdapterConfig:
    config = RuntimeAdapterConfig()
    for path in runtime_config_paths(workspace):
        if not os.path.exists(path):
            continue
        config = RuntimeAdapterConfig.from_dict(_load_config_file(path), base=config)
    return config


def _load_config_file(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        if path.endswith(".json"):
            data = json.load(handle) or {}
        else:
            data = yaml.safe_load(handle) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"Runtime config file must contain a mapping: {path}")
    return dict(data)


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))
