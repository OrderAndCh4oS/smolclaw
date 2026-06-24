import os
from dataclasses import dataclass

from app.model_defaults import (
    MODEL_PREFIX_OPENAI_GPT54,
    MODEL_PREFIX_OPENAI_GPT55,
)


REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
DEFAULT_REASONING_EFFORT = os.getenv("REASONING_EFFORT", "medium") or None


@dataclass(frozen=True)
class ModelCapabilities:
    provider: str
    model_prefix: str
    endpoint_family: str
    supports_tools: bool
    supports_reasoning_effort: bool
    supports_streaming: bool
    supports_structured_output: bool
    max_context_tokens: int | None
    default_effort: str | None
    text_endpoint: str
    tool_endpoint: str
    reasoning_tool_endpoint: str


class ModelRegistry:
    def __init__(self, capabilities: list[ModelCapabilities] | None = None):
        self._capabilities = capabilities or [
            ModelCapabilities(
                provider="openai",
                model_prefix=MODEL_PREFIX_OPENAI_GPT55,
                endpoint_family="responses",
                supports_tools=True,
                supports_reasoning_effort=True,
                supports_streaming=True,
                supports_structured_output=True,
                max_context_tokens=None,
                default_effort=DEFAULT_REASONING_EFFORT,
                text_endpoint="chat.completions",
                tool_endpoint="chat.completions",
                reasoning_tool_endpoint="responses",
            ),
            ModelCapabilities(
                provider="openai",
                model_prefix=MODEL_PREFIX_OPENAI_GPT54,
                endpoint_family="responses",
                supports_tools=True,
                supports_reasoning_effort=True,
                supports_streaming=True,
                supports_structured_output=True,
                max_context_tokens=None,
                default_effort=DEFAULT_REASONING_EFFORT,
                text_endpoint="chat.completions",
                tool_endpoint="chat.completions",
                reasoning_tool_endpoint="responses",
            ),
        ]

    def resolve(self, model: str | None) -> ModelCapabilities | None:
        if not model:
            return None
        matches = [
            caps for caps in self._capabilities
            if model.startswith(caps.model_prefix)
        ]
        if not matches:
            return None
        return max(matches, key=lambda caps: len(caps.model_prefix))

    def is_switchable_model(self, model: str) -> bool:
        return self.resolve(model) is not None

    def default_effort(self, model: str | None) -> str | None:
        caps = self.resolve(model)
        return caps.default_effort if caps else None

    def supports_reasoning_effort(self, model: str | None) -> bool:
        caps = self.resolve(model)
        return bool(caps and caps.supports_reasoning_effort)

    def endpoint_for(
        self,
        model: str | None,
        *,
        tools: bool = False,
        reasoning_effort: str | None = None,
    ) -> str:
        caps = self.resolve(model)
        if caps is None:
            return "chat.completions"
        if tools and reasoning_effort and caps.supports_reasoning_effort:
            return caps.reasoning_tool_endpoint
        if tools:
            return caps.tool_endpoint
        return caps.text_endpoint

    def validate(self, model: str, reasoning_effort: str | None = None):
        caps = self.resolve(model)
        if caps is None:
            raise ValueError(
                "Model must start with "
                f"{MODEL_PREFIX_OPENAI_GPT54} or {MODEL_PREFIX_OPENAI_GPT55}."
            )
        if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
            valid = ", ".join(sorted(REASONING_EFFORTS))
            raise ValueError(f"Reasoning effort must be one of: {valid}.")
        if reasoning_effort is not None and not caps.supports_reasoning_effort:
            raise ValueError(f"Model {model} does not support reasoning effort.")
        return caps

    def describe(self, model: str | None, reasoning_effort: str | None = None) -> str:
        caps = self.resolve(model)
        if caps is None:
            return "provider:unknown endpoint:chat.completions compatibility:unknown"
        tool_endpoint = self.endpoint_for(
            model,
            tools=True,
            reasoning_effort=reasoning_effort or caps.default_effort,
        )
        max_context = (
            f"{caps.max_context_tokens:,}"
            if caps.max_context_tokens is not None
            else "unknown"
        )
        reasoning = "yes" if caps.supports_reasoning_effort else "no"
        streaming = "yes" if caps.supports_streaming else "no"
        structured = "yes" if caps.supports_structured_output else "no"
        return (
            f"provider:{caps.provider} text:{caps.text_endpoint} tools:{tool_endpoint} "
            f"reasoning:{reasoning} streaming:{streaming} structured:{structured} "
            f"max_context:{max_context}"
        )


MODEL_REGISTRY = ModelRegistry()
