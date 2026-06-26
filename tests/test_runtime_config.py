import os

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
