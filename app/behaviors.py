from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class LoopBehavior:
    name: str
    before_first_llm_prompt: str | None = None
    after_tools_prompt: str | None = None


PLANNING_BEHAVIOR = LoopBehavior(
    name="plan",
    before_first_llm_prompt=(
        "Before acting, think through your approach: "
        "What is the user asking for? What information do you need? "
        "What's the best sequence of steps? Which tools should you use and in what order? "
        "Keep this planning internal; do not narrate it to the user. Execute with tools, then answer when done."
    ),
    after_tools_prompt=(
        "Review the tool results above. What did you learn? "
        "Does this change your approach? Keep this assessment internal. Continue with tools if needed, otherwise answer."
    ),
)

REFLECTION_BEHAVIOR = LoopBehavior(
    name="reflect",
    after_tools_prompt=(
        "Before continuing, assess: Have you gathered enough information to answer completely? "
        "Are your findings verified against sources? Is anything missing or uncertain? "
        "Keep this assessment internal. If incomplete, continue working with tools. If complete, provide your final answer."
    ),
)

BEHAVIOR_LIBRARY = {
    PLANNING_BEHAVIOR.name: PLANNING_BEHAVIOR,
    REFLECTION_BEHAVIOR.name: REFLECTION_BEHAVIOR,
}


def resolve_behavior_names(config) -> list[str]:
    names = list(getattr(config, "behaviors", []) or [])
    if getattr(config, "planning", False) and "plan" not in names:
        names.append("plan")
    if getattr(config, "reflection", False) and "reflect" not in names:
        names.append("reflect")
    return names


def load_behaviors(names: Iterable[str]) -> list[LoopBehavior]:
    return [BEHAVIOR_LIBRARY[name] for name in names if name in BEHAVIOR_LIBRARY]
