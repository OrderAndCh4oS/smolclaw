from dataclasses import dataclass
from unittest.mock import Mock

from app.llm import detect_provider
from app.model_defaults import (
    DEFAULT_ANTHROPIC_CHAT_MODEL,
    DEFAULT_OPENAI_CHAT_MODEL,
    DEFAULT_OPENAI_MEMORY_QUERY_MODEL,
    DEFAULT_SUBAGENT_MODEL,
    MODEL_EXAMPLES,
    MODEL_SELECTION_PATTERN,
    MODEL_SWITCHABLE_PREFIXES,
)
from app.model_registry import MODEL_REGISTRY


@dataclass(frozen=True)
class ModelSelection:
    model: str
    reasoning_effort: str | None = None


class RuntimeModelSettings:
    def __init__(
        self,
        default_selection: ModelSelection | None = None,
        subagent_selection: ModelSelection | None = None,
    ):
        self.default_selection: ModelSelection | None = default_selection
        self.subagent_selection = subagent_selection or ModelSelection(
            model=DEFAULT_SUBAGENT_MODEL,
            reasoning_effort=MODEL_REGISTRY.default_effort(DEFAULT_SUBAGENT_MODEL),
        )

    def set_default(self, selection: ModelSelection):
        self.default_selection = selection

    def set_subagent_default(self, selection: ModelSelection):
        self.subagent_selection = selection

    def resolve(self, fallback_model: str, *, subagent: bool = False) -> ModelSelection:
        if subagent:
            return self.subagent_selection
        if self.default_selection is not None:
            return self.default_selection
        return ModelSelection(model=fallback_model)


def is_switchable_model(model: str) -> bool:
    return MODEL_REGISTRY.is_switchable_model(model)


def parse_model_selection(value: str) -> ModelSelection:
    parts = value.split()
    if not parts:
        raise ValueError(f"Usage: /model <{MODEL_SELECTION_PATTERN}> [none|minimal|low|medium|high|xhigh]")
    model = parts[0]
    if len(parts) > 2:
        raise ValueError(f"Usage: /model <{MODEL_SELECTION_PATTERN}> [none|minimal|low|medium|high|xhigh]")
    reasoning_effort = parts[1] if len(parts) == 2 else None
    MODEL_REGISTRY.validate(model, reasoning_effort)
    return ModelSelection(model=model, reasoning_effort=reasoning_effort)


def completion_provider(llm):
    provider = getattr(llm, "completion_provider", None)
    if provider is None or isinstance(provider, Mock):
        return llm
    return provider


def get_model(llm) -> str:
    provider = completion_provider(llm)
    return str(getattr(provider, "completion_model", "unknown"))


def get_reasoning_effort(llm) -> str | None:
    provider = completion_provider(llm)
    value = getattr(provider, "reasoning_effort", None)
    return value if isinstance(value, str) and value else None


def apply_model_selection(llm, selection: ModelSelection):
    provider = completion_provider(llm)
    current_provider = detect_provider(str(getattr(provider, "completion_model", "") or ""))
    next_provider = detect_provider(selection.model)
    if current_provider != next_provider:
        raise ValueError(
            f"Cannot switch provider from {current_provider} to {next_provider} at runtime. "
            f"Restart with --model {selection.model}."
        )
    provider.completion_model = selection.model
    effort = selection.reasoning_effort
    if effort is None:
        effort = MODEL_REGISTRY.default_effort(selection.model)
    setattr(provider, "reasoning_effort", effort)


def apply_runtime_model_selection(llm, selection: ModelSelection, model_settings=None):
    apply_model_selection(llm, selection)
    if model_settings is not None and not isinstance(model_settings, Mock):
        model_settings.set_default(selection)


def apply_subagent_model_selection(selection: ModelSelection, model_settings=None):
    if model_settings is not None and not isinstance(model_settings, Mock):
        model_settings.set_subagent_default(selection)


def model_status(llm) -> str:
    model = get_model(llm)
    effort = get_reasoning_effort(llm)
    suffix = f" effort:{effort}" if effort else ""
    details = MODEL_REGISTRY.describe(model, effort)
    return f"model:{model}{suffix} {details}"


def selection_status(selection: ModelSelection) -> str:
    suffix = f" effort:{selection.reasoning_effort}" if selection.reasoning_effort else ""
    details = MODEL_REGISTRY.describe(selection.model, selection.reasoning_effort)
    return f"model:{selection.model}{suffix} {details}"


def subagent_model_status(model_settings=None) -> str:
    if model_settings is None or isinstance(model_settings, Mock):
        selection = RuntimeModelSettings().subagent_selection
    else:
        selection = model_settings.resolve("unknown", subagent=True)
    return f"subagents {selection_status(selection)}"


def model_help(llm, model_settings=None) -> str:
    examples = "\n".join(
        f"  /model {model} high" if model.startswith("gpt-") else f"  /model {model}"
        for model in MODEL_EXAMPLES
    )
    return "\n".join([
        f"Current {model_status(llm)}",
        f"Current {subagent_model_status(model_settings)}",
        "Usage:",
        "  /model                         Show current model",
        "  /model list                    Show switchable model examples",
        f"  /model <{MODEL_SELECTION_PATTERN}> [effort]",
        f"  /model subagents <{MODEL_SELECTION_PATTERN}> [effort]",
        "Effort: none, minimal, low, medium, high, xhigh.",
        "Endpoint behavior: OpenAI reasoning tool turns use Responses.",
        "Examples:",
        examples,
        f"  /model subagents {DEFAULT_SUBAGENT_MODEL} medium",
    ])


def model_list() -> str:
    return "\n".join([
        f"Switchable model prefixes: {MODEL_SWITCHABLE_PREFIXES}",
        "Compatibility:",
        f"  {DEFAULT_OPENAI_CHAT_MODEL}*: {MODEL_REGISTRY.describe(DEFAULT_OPENAI_CHAT_MODEL, 'medium')}",
        f"  gpt-5.4*: {MODEL_REGISTRY.describe(DEFAULT_OPENAI_MEMORY_QUERY_MODEL, 'medium')}",
        f"  claude-*: {MODEL_REGISTRY.describe(DEFAULT_ANTHROPIC_CHAT_MODEL)}",
        "Examples:",
        *[f"  {model}" for model in MODEL_EXAMPLES],
    ])
