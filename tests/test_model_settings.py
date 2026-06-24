import pytest

from app.model_settings import (
    apply_model_selection,
    apply_subagent_model_selection,
    model_list,
    model_status,
    ModelSelection,
    parse_model_selection,
    RuntimeModelSettings,
    subagent_model_status,
)
from app.model_registry import MODEL_REGISTRY


class FakeLlm:
    completion_model = "gpt-5.4-mini"
    reasoning_effort = None


def test_parse_model_selection_accepts_gpt_55_high_effort():
    selection = parse_model_selection("gpt-5.5 high")

    assert selection.model == "gpt-5.5"
    assert selection.reasoning_effort == "high"


def test_parse_model_selection_accepts_any_gpt_54_or_55_suffix():
    selection = parse_model_selection("gpt-5.4-codex-max xhigh")

    assert selection.model == "gpt-5.4-codex-max"
    assert selection.reasoning_effort == "xhigh"


def test_parse_model_selection_rejects_other_models():
    with pytest.raises(ValueError, match="gpt-5.4 or gpt-5.5"):
        parse_model_selection("gpt-4.1 high")


def test_apply_model_selection_updates_model_and_effort():
    llm = FakeLlm()

    apply_model_selection(llm, parse_model_selection("gpt-5.5-pro high"))

    assert llm.completion_model == "gpt-5.5-pro"
    assert llm.reasoning_effort == "high"
    status = model_status(llm)
    assert status.startswith("model:gpt-5.5-pro effort:high")
    assert "provider:openai" in status
    assert "tools:responses" in status


def test_apply_model_selection_defaults_reasoning_effort_from_registry():
    llm = FakeLlm()
    llm.reasoning_effort = "high"

    apply_model_selection(llm, parse_model_selection("gpt-5.5"))

    assert llm.completion_model == "gpt-5.5"
    assert llm.reasoning_effort == MODEL_REGISTRY.default_effort("gpt-5.5")


def test_apply_model_selection_rejects_runtime_provider_swap():
    llm = FakeLlm()

    with pytest.raises(ValueError, match="Cannot switch provider"):
        apply_model_selection(llm, ModelSelection("claude-sonnet-4-20250514"))


def test_runtime_model_settings_use_openai_default_for_subagents():
    settings = RuntimeModelSettings()

    selection = settings.resolve("gpt-5.4-mini", subagent=True)

    assert selection.model == "gpt-5.5"
    assert selection.reasoning_effort == MODEL_REGISTRY.default_effort("gpt-5.5")


def test_apply_subagent_model_selection_updates_subagent_default_only():
    settings = RuntimeModelSettings()
    llm = FakeLlm()

    apply_subagent_model_selection(parse_model_selection("gpt-5.4-pro high"), settings)

    assert llm.completion_model == "gpt-5.4-mini"
    assert settings.resolve("fallback", subagent=True).model == "gpt-5.4-pro"
    assert settings.resolve("fallback", subagent=True).reasoning_effort == "high"
    status = subagent_model_status(settings)
    assert status.startswith("subagents model:gpt-5.4-pro effort:high")
    assert "tools:responses" in status


def test_runtime_model_settings_keep_top_level_fallback_without_default():
    settings = RuntimeModelSettings()

    selection = settings.resolve("gpt-5.4-mini")

    assert selection.model == "gpt-5.4-mini"
    assert selection.reasoning_effort is None


def test_model_registry_routes_reasoning_tool_turns_to_responses():
    assert MODEL_REGISTRY.endpoint_for("gpt-5.5", tools=True, reasoning_effort="high") == "responses"
    assert MODEL_REGISTRY.endpoint_for("gpt-5.5", tools=True, reasoning_effort=None) == "chat.completions"
    assert MODEL_REGISTRY.endpoint_for("unknown", tools=True, reasoning_effort="high") == "chat.completions"


def test_model_list_includes_compatibility_details():
    output = model_list()

    assert "Compatibility:" in output
    assert "gpt-5.5*" in output
    assert "tools:responses" in output
