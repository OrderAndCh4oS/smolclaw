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
class CommandSandboxConfig:
    image: str | None = None
    network: str = "none"
    approved_network: str = "bridge"
    cpus: str = "2"
    memory: str = "2g"
    pids_limit: int = 256
    tmpfs_size: str = "512m"
    read_only_root: bool = True
    env_allowlist: tuple[str, ...] | None = None
    network_proxy_env: dict[str, str] = field(default_factory=dict)
    auto_pull: bool = True
    auto_build: bool = False
    build_context: str | None = None
    build_dockerfile: str | None = None

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any] | None,
        *,
        base: "CommandSandboxConfig | None" = None,
    ) -> "CommandSandboxConfig":
        baseline = base or cls()
        if not isinstance(data, Mapping):
            return baseline
        network = str(data.get("network") or baseline.network)
        if network != "none":
            raise ValueError("Unsupported command sandbox network mode: only 'none' is supported.")
        approved_network = str(data.get("approved_network") or baseline.approved_network)
        if approved_network not in {"bridge", "none"}:
            raise ValueError("Unsupported approved command sandbox network mode: expected 'bridge' or 'none'.")
        env_allowlist = data.get("env_allowlist", baseline.env_allowlist)
        if env_allowlist is not None:
            if isinstance(env_allowlist, str):
                env_allowlist = (env_allowlist,)
            else:
                env_allowlist = tuple(str(item) for item in env_allowlist)
        network_proxy_env = data.get("network_proxy_env", baseline.network_proxy_env)
        if not isinstance(network_proxy_env, Mapping):
            network_proxy_env = {}
        return cls(
            image=str(data["image"]) if data.get("image") else baseline.image,
            network=network,
            approved_network=approved_network,
            cpus=str(data.get("cpus") or baseline.cpus),
            memory=str(data.get("memory") or baseline.memory),
            pids_limit=int(data.get("pids_limit") or baseline.pids_limit),
            tmpfs_size=str(data.get("tmpfs_size") or baseline.tmpfs_size),
            read_only_root=_coerce_bool(data.get("read_only_root", baseline.read_only_root)),
            env_allowlist=env_allowlist,
            network_proxy_env={str(key): str(value) for key, value in network_proxy_env.items()},
            auto_pull=_coerce_bool(data.get("auto_pull", baseline.auto_pull)),
            auto_build=_coerce_bool(data.get("auto_build", baseline.auto_build)),
            build_context=str(data["build_context"]) if data.get("build_context") else baseline.build_context,
            build_dockerfile=str(data["build_dockerfile"]) if data.get("build_dockerfile") else baseline.build_dockerfile,
        )

    def to_dict(self) -> dict:
        payload: dict[str, Any] = {
            "network": self.network,
            "approved_network": self.approved_network,
            "cpus": self.cpus,
            "memory": self.memory,
            "pids_limit": self.pids_limit,
            "tmpfs_size": self.tmpfs_size,
            "read_only_root": self.read_only_root,
            "auto_pull": self.auto_pull,
            "auto_build": self.auto_build,
        }
        if self.image:
            payload["image"] = self.image
        if self.env_allowlist is not None:
            payload["env_allowlist"] = list(self.env_allowlist)
        if self.network_proxy_env:
            payload["network_proxy_env"] = dict(self.network_proxy_env)
        if self.build_context:
            payload["build_context"] = self.build_context
        if self.build_dockerfile:
            payload["build_dockerfile"] = self.build_dockerfile
        return payload


@dataclass(frozen=True)
class CommandAdapterConfig(AdapterSelection):
    sandbox: CommandSandboxConfig = field(default_factory=CommandSandboxConfig)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any] | None,
        *,
        base: "CommandAdapterConfig",
    ) -> "CommandAdapterConfig":
        if not isinstance(data, Mapping):
            return base
        adapter_data = data.get("default") if isinstance(data.get("default"), Mapping) else data
        selection = AdapterSelection.from_dict(adapter_data, base=base)
        sandbox_data = data.get("sandbox") if isinstance(data.get("sandbox"), Mapping) else None
        return cls(
            provider=selection.provider,
            model=selection.model,
            sandbox=CommandSandboxConfig.from_dict(sandbox_data, base=base.sandbox),
        )

    def to_dict(self) -> dict:
        payload = super().to_dict()
        sandbox = self.sandbox.to_dict()
        if sandbox:
            payload["sandbox"] = sandbox
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
    command: CommandAdapterConfig = field(default_factory=lambda: CommandAdapterConfig("subprocess"))

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
            command=CommandAdapterConfig.from_dict(adapters.get("command"), base=baseline.command),
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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


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
