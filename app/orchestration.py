"""Composable orchestration patterns for multi-agent workflows."""

import asyncio
import logging
import re
from typing import Dict, List, Optional

from app.agent_config import AgentConfig
from app.agent_factory import build_agent_loop
from app.session import SessionManager
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


async def sequential_pipeline(
    agent_names: List[str],
    initial_input: str,
    configs: Dict[str, AgentConfig],
    master_registry: ToolRegistry,
    smol_rag,
    session_manager: SessionManager,
) -> str:
    """Chain agents in sequence: output of agent N becomes input of agent N+1.

    :param agent_names: Ordered list of agent config names.
    :param initial_input: Input text for the first agent.
    :returns: The final agent's output.
    """
    current_input = initial_input

    for i, agent_name in enumerate(agent_names):
        if agent_name not in configs:
            return f"Error: unknown agent '{agent_name}'"

        loop = build_agent_loop(
            configs[agent_name], master_registry, smol_rag,
            session_manager, session_key_prefix=f"seq-{i}",
        )
        try:
            current_input = await loop.process(current_input)
        finally:
            await loop.close()

    return current_input


async def fanout_pipeline(
    agent_names: List[str],
    input_text: str,
    configs: Dict[str, AgentConfig],
    master_registry: ToolRegistry,
    smol_rag,
    session_manager: SessionManager,
    timeout: float = 300,
) -> List[str]:
    """Run multiple agents in parallel on the same input.

    :param agent_names: List of agent config names to run concurrently.
    :param input_text: Input text sent to all agents.
    :param timeout: Max seconds to wait for all agents.
    :returns: List of results (one per agent, in order). Errors for failed agents.
    """
    loops = []
    for i, agent_name in enumerate(agent_names):
        if agent_name not in configs:
            loops.append(None)
            continue
        loop = build_agent_loop(
            configs[agent_name], master_registry, smol_rag,
            session_manager, session_key_prefix=f"fan-{i}",
        )
        loops.append(loop)

    async def _run(loop, name):
        if loop is None:
            return f"Error: unknown agent '{name}'"
        try:
            return await loop.process(input_text)
        except Exception as e:
            return f"Error: agent '{name}' failed — {e}"
        finally:
            await loop.close()

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[_run(loop, name) for loop, name in zip(loops, agent_names)]),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # Close any loops that are still running
        for loop in loops:
            if loop and not loop._closed:
                await loop.close()
        return [f"Error: fanout timed out after {timeout}s"] * len(agent_names)

    return list(results)


async def route(
    input_text: str,
    routes: Dict[str, str],
    configs: Dict[str, AgentConfig],
    master_registry: ToolRegistry,
    smol_rag,
    session_manager: SessionManager,
    llm=None,
) -> str:
    """Route input to a single agent based on pattern matching or LLM classification.

    :param input_text: The input to route.
    :param routes: Mapping of pattern/keyword → agent_name.
    :param llm: Optional LLM for classification-based routing. If None, uses pattern matching.
    :returns: The selected agent's output.
    """
    selected_agent = None

    if llm and hasattr(llm, "get_structured_completion"):
        # LLM-based routing with structured output
        try:
            from app.schemas import RouteDecision
            route_descriptions = "\n".join(f"- {key}: routes to '{agent}'" for key, agent in routes.items())
            prompt = (
                f"Given the following input, decide which route best matches.\n\n"
                f"Available routes:\n{route_descriptions}\n\n"
                f"Input: {input_text}\n\n"
                f"Select the route key that best matches."
            )
            decision = await llm.get_structured_completion(prompt, RouteDecision)
            if decision.selected_route in routes:
                selected_agent = routes[decision.selected_route]
                logger.info("LLM routed to '%s' (confidence=%.2f)", selected_agent, decision.confidence)
        except Exception as e:
            logger.warning("LLM routing failed, falling back to pattern matching: %s", e)

    # Pattern matching fallback
    if not selected_agent:
        lower_input = input_text.lower()
        for pattern, agent_name in routes.items():
            if re.search(pattern, lower_input, re.IGNORECASE):
                selected_agent = agent_name
                logger.info("Pattern matched '%s' → '%s'", pattern, agent_name)
                break

    if not selected_agent:
        # Default to first route
        selected_agent = next(iter(routes.values()), None)
        if not selected_agent:
            return "Error: no routes configured"
        logger.info("No match found, defaulting to '%s'", selected_agent)

    if selected_agent not in configs:
        return f"Error: unknown agent '{selected_agent}'"

    loop = build_agent_loop(
        configs[selected_agent], master_registry, smol_rag,
        session_manager, session_key_prefix="route",
    )
    try:
        return await loop.process(input_text)
    finally:
        await loop.close()
