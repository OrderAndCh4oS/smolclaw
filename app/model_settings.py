from dataclasses import dataclass
from unittest.mock import Mock


REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
SWITCHABLE_MODEL_PREFIXES = ("gpt-5.4", "gpt-5.5")
MODEL_EXAMPLES = [
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.5-mini",
    "gpt-5.4",
    "gpt-5.4-mini",
]


@dataclass(frozen=True)
class ModelSelection:
    model: str
    reasoning_effort: str | None = None


class RuntimeModelSettings:
    def __init__(self):
        self.default_selection: ModelSelection | None = None
        self.subagent_selection = ModelSelection(model="gpt-5.5", reasoning_effort="medium")

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
    return bool(model and model.startswith(SWITCHABLE_MODEL_PREFIXES))


def parse_model_selection(value: str) -> ModelSelection:
    parts = value.split()
    if not parts:
        raise ValueError("Usage: /model <gpt-5.4*|gpt-5.5*> [none|minimal|low|medium|high|xhigh]")
    model = parts[0]
    if not is_switchable_model(model):
        raise ValueError("Model must start with gpt-5.4 or gpt-5.5.")
    if len(parts) > 2:
        raise ValueError("Usage: /model <gpt-5.4*|gpt-5.5*> [none|minimal|low|medium|high|xhigh]")
    reasoning_effort = parts[1] if len(parts) == 2 else None
    if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
        valid = ", ".join(sorted(REASONING_EFFORTS))
        raise ValueError(f"Reasoning effort must be one of: {valid}.")
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
    provider.completion_model = selection.model
    if selection.reasoning_effort is not None:
        setattr(provider, "reasoning_effort", selection.reasoning_effort)


def apply_runtime_model_selection(llm, selection: ModelSelection, model_settings=None):
    apply_model_selection(llm, selection)
    if model_settings is not None and not isinstance(model_settings, Mock):
        model_settings.set_default(selection)


def apply_subagent_model_selection(selection: ModelSelection, model_settings=None):
    if model_settings is not None and not isinstance(model_settings, Mock):
        model_settings.set_subagent_default(selection)


def model_status(llm) -> str:
    effort = get_reasoning_effort(llm)
    suffix = f" effort:{effort}" if effort else ""
    return f"model:{get_model(llm)}{suffix}"


def selection_status(selection: ModelSelection) -> str:
    suffix = f" effort:{selection.reasoning_effort}" if selection.reasoning_effort else ""
    return f"model:{selection.model}{suffix}"


def subagent_model_status(model_settings=None) -> str:
    if model_settings is None or isinstance(model_settings, Mock):
        selection = RuntimeModelSettings().subagent_selection
    else:
        selection = model_settings.resolve("unknown", subagent=True)
    return f"subagents {selection_status(selection)}"


def model_help(llm, model_settings=None) -> str:
    examples = "\n".join(f"  /model {model} high" for model in MODEL_EXAMPLES)
    return "\n".join([
        f"Current {model_status(llm)}",
        f"Current {subagent_model_status(model_settings)}",
        "Usage:",
        "  /model                         Show current model",
        "  /model list                    Show switchable model examples",
        "  /model <gpt-5.4*|gpt-5.5*> [effort]",
        "  /model subagents <gpt-5.4*|gpt-5.5*> [effort]",
        "Effort: none, minimal, low, medium, high, xhigh",
        "Examples:",
        examples,
        "  /model subagents gpt-5.5 medium",
    ])


def model_list() -> str:
    return "\n".join([
        "Switchable model prefixes: gpt-5.4*, gpt-5.5*",
        "Examples:",
        *[f"  {model}" for model in MODEL_EXAMPLES],
    ])
