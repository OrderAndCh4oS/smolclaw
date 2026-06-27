import os

import pytest

from app.runtime_config import RuntimeAdapterConfig, load_runtime_config
from app.workspace import WorkspaceContext


def test_load_runtime_config_uses_workspace_yaml(temp_dir):
    workspace = WorkspaceContext.from_root(temp_dir).ensure_dirs()
    path = os.path.join(workspace.state_root_dir, "config.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join([
                "adapters:",
                "  llm:",
                "    default:",
                "      provider: anthropic",
                "      model: claude-sonnet-4-20250514",
                "    embeddings:",
                "      provider: openai",
                "      model: text-embedding-3-small",
                "  task_source:",
                "    default:",
                "      provider: jira",
                "  code_review:",
                "    default:",
                "      provider: github",
            ])
        )

    config = load_runtime_config(workspace)

    assert config.llm.default.provider == "anthropic"
    assert config.llm.default.model == "claude-sonnet-4-20250514"
    assert config.llm.embeddings.provider == "openai"
    assert config.task_source.provider == "jira"


def test_runtime_config_merges_partial_adapter_config():
    base = RuntimeAdapterConfig()
    config = RuntimeAdapterConfig.from_dict({
        "adapters": {
            "llm": {
                "memory_query": {
                    "model": "gpt-5.4-pro",
                },
            },
        },
    }, base=base)

    assert config.llm.default == base.llm.default
    assert config.llm.memory_query.provider == "openai"
    assert config.llm.memory_query.model == "gpt-5.4-pro"


def test_runtime_config_loads_command_sandbox_config():
    config = RuntimeAdapterConfig.from_dict({
        "adapters": {
            "command": {
                "default": {
                    "provider": "docker",
                    "model": "legacy-image:latest",
                },
                "sandbox": {
                    "image": "project-image:latest",
                    "cpus": "4",
                    "memory": "4g",
                    "pids_limit": 512,
                    "tmpfs_size": "1g",
                    "read_only_root": False,
                    "env_allowlist": ["CI", "LANG", "CUSTOM_FLAG"],
                    "approved_network": "bridge",
                    "network_proxy_env": {"HTTPS_PROXY": "http://proxy.local:8080"},
                    "auto_pull": False,
                    "auto_build": True,
                    "build_context": ".",
                    "build_dockerfile": "Dockerfile.sandbox",
                },
            },
        },
    })

    assert config.command.provider == "docker"
    assert config.command.model == "legacy-image:latest"
    assert config.command.sandbox.image == "project-image:latest"
    assert config.command.sandbox.cpus == "4"
    assert config.command.sandbox.memory == "4g"
    assert config.command.sandbox.pids_limit == 512
    assert config.command.sandbox.tmpfs_size == "1g"
    assert config.command.sandbox.read_only_root is False
    assert config.command.sandbox.env_allowlist == ("CI", "LANG", "CUSTOM_FLAG")
    assert config.command.sandbox.approved_network == "bridge"
    assert config.command.sandbox.network_proxy_env == {"HTTPS_PROXY": "http://proxy.local:8080"}
    assert config.command.sandbox.auto_pull is False
    assert config.command.sandbox.auto_build is True
    assert config.command.sandbox.build_context == "."
    assert config.command.sandbox.build_dockerfile == "Dockerfile.sandbox"


def test_runtime_config_rejects_unsupported_command_sandbox_network():
    with pytest.raises(ValueError, match="only 'none' is supported"):
        RuntimeAdapterConfig.from_dict({
            "adapters": {
                "command": {
                    "provider": "docker",
                    "sandbox": {"network": "bridge"},
                },
            },
        })


def test_runtime_config_rejects_unsupported_approved_command_sandbox_network():
    with pytest.raises(ValueError, match="approved command sandbox network"):
        RuntimeAdapterConfig.from_dict({
            "adapters": {
                "command": {
                    "provider": "docker",
                    "sandbox": {"approved_network": "host"},
                },
            },
        })
