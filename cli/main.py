import asyncio
import logging
import os
import sys
from typing import Optional

import typer

# Suppress noisy loggers from printing to console
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("mini-rag").propagate = False
from rich.console import Console
from rich.markdown import Markdown
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from app.agent_loop import AgentLoop
from app.context_builder import ContextBuilder
from app.definitions import (
    SESSIONS_DIR, MEMORY_DOCS_DIR, WORKSPACE_DIR, AGENT_MODEL,
    MAX_ITERATIONS, MEMORY_WINDOW,
)
from app.llm import create_llm
from app.session import SessionManager
from app.smol_rag import SmolRag
from app.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from app.tools.memory_tools import MemorySearchTool, MemoryGraphQueryTool, MemoryStoreTool, MemoryRelateTool
from app.tools.registry import ToolRegistry
from app.tools.shell import ExecTool
from app.tools.web import WebSearchTool, WebFetchTool
from app.utilities import ensure_dir

app = typer.Typer(help="SmolClaw — agentic assistant with persistent memory")
console = Console()

DEFAULT_AGENTS_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.yaml")


def _build_tool_registry(smol_rag: SmolRag, workspace: str) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool(allowed_dir=workspace))
    registry.register(WriteFileTool(allowed_dir=workspace))
    registry.register(EditFileTool(allowed_dir=workspace))
    registry.register(ListDirTool(allowed_dir=workspace))
    registry.register(ExecTool())
    registry.register(MemorySearchTool(smol_rag))
    registry.register(MemoryGraphQueryTool(smol_rag))
    registry.register(MemoryStoreTool(smol_rag, ensure_dir(MEMORY_DOCS_DIR)))
    registry.register(MemoryRelateTool(smol_rag))
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    return registry


def _build_multiagent(
    agent_name: str,
    agents_config_path: str,
    session_key: str,
    smol_rag: SmolRag,
    workspace: str,
    session_manager: SessionManager,
) -> AgentLoop:
    from app.agent_config import AgentConfigLoader
    from app.agent_factory import build_agent_loop
    from app.subagent import SubagentManager
    from app.tools.spawn import SpawnTool, GetResultTool, AwaitResultTool

    configs = AgentConfigLoader.load(agents_config_path)
    if agent_name not in configs:
        available = ", ".join(sorted(configs.keys()))
        raise typer.BadParameter(f"Unknown agent '{agent_name}'. Available: {available}")

    master_registry = _build_tool_registry(smol_rag, workspace)

    subagent_manager = SubagentManager(
        configs=configs,
        master_registry=master_registry,
        smol_rag=smol_rag,
        session_manager=session_manager,
    )
    master_registry.register(SpawnTool(subagent_manager))
    master_registry.register(GetResultTool(subagent_manager))
    master_registry.register(AwaitResultTool(subagent_manager))

    return build_agent_loop(
        config=configs[agent_name],
        master_registry=master_registry,
        smol_rag=smol_rag,
        session_manager=session_manager,
        session_key_prefix=session_key,
    )


@app.command()
def chat(
    session_key: str = typer.Option("default", "--session", "-s", help="Session key"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace directory"),
    model: str = typer.Option(AGENT_MODEL, "--model", "-m", help="LLM model to use"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name from agents.yaml"),
    agents_config: str = typer.Option(DEFAULT_AGENTS_CONFIG, "--agents-config", help="Path to agents YAML config"),
):
    """Start an interactive chat session."""
    asyncio.run(_chat_loop(session_key, workspace, model, agent, agents_config))


async def _chat_loop(
    session_key: str,
    workspace: str,
    model: str,
    agent_name: Optional[str] = None,
    agents_config: str = DEFAULT_AGENTS_CONFIG,
):
    ensure_dir(SESSIONS_DIR)

    smol_rag = SmolRag()
    session_manager = SessionManager(SESSIONS_DIR)

    if agent_name:
        agent = _build_multiagent(
            agent_name, agents_config, session_key, smol_rag, workspace, session_manager,
        )
        label = agent_name.capitalize()
    else:
        llm = create_llm(completion_model=model)
        registry = _build_tool_registry(smol_rag, workspace)

        bootstrap_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "AGENT.md")
        context_builder = ContextBuilder(shared_bootstrap_path=bootstrap_path)

        session = session_manager.get_or_create(session_key)

        agent = AgentLoop(
            llm=llm,
            tool_registry=registry,
            context_builder=context_builder,
            session=session,
            session_manager=session_manager,
            max_iterations=MAX_ITERATIONS,
            memory_window=MEMORY_WINDOW,
            smol_rag=smol_rag,
        )
        label = "SmolClaw"

    history_file = os.path.join(SESSIONS_DIR, "prompt_history.txt")
    prompt_session = PromptSession(history=FileHistory(history_file))

    console.print(f"[bold green]{label}[/bold green] ready. Type /quit to exit.\n")

    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: prompt_session.prompt("you> ")
            )
        except (EOFError, KeyboardInterrupt):
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input in ("/quit", "/exit"):
            break
        if user_input == "/clear":
            agent.session.clear()
            session_manager.save(agent.session)
            console.print("[dim]Session cleared.[/dim]")
            continue

        with console.status("[bold cyan]thinking...[/bold cyan]"):
            response = await agent.process(user_input)

        console.print()
        console.print(Markdown(response))
        console.print()


@app.command()
def ingest(
    path: str = typer.Argument(..., help="File or directory to ingest"),
):
    """Ingest documents into memory."""
    asyncio.run(_ingest(path))


async def _ingest(path: str):
    from app.utilities import get_docs, make_hash
    smol_rag = SmolRag()

    if os.path.isfile(path):
        files = [path]
    elif os.path.isdir(path):
        files = get_docs(path)
    else:
        console.print(f"[red]Not found:[/red] {path}")
        return

    ingested = 0
    skipped = 0
    for file_path in files:
        with open(file_path) as f:
            content = f.read()

        doc_id = make_hash(content, "doc_")
        if await smol_rag.source_doc_map.has_left(file_path) and await smol_rag.source_doc_map.equal_right(file_path, doc_id):
            console.print(f"[dim]Skipped (unchanged):[/dim] {file_path}")
            skipped += 1
            continue

        await smol_rag.ingest_text(content, source_id=file_path, save=False)
        console.print(f"[green]Ingested:[/green] {file_path}")
        ingested += 1

    if ingested > 0:
        await smol_rag._save_stores()
    console.print(f"\n[bold]Done:[/bold] {ingested} ingested, {skipped} skipped")


@app.command()
def watch(
    memory_dir: str = typer.Option(
        MEMORY_DOCS_DIR, "--memory-dir", "-d", help="Memory directory to watch",
    ),
    interval: float = typer.Option(5.0, "--interval", "-i", help="Poll interval in seconds"),
):
    """Watch the memory directory for changes and re-ingest."""
    asyncio.run(_watch(memory_dir, interval))


async def _watch(memory_dir: str, interval: float):
    from app.watcher import MemoryFileWatcher
    smol_rag = SmolRag()
    watcher = MemoryFileWatcher(memory_dir, smol_rag, poll_interval=interval)
    console.print(f"[bold green]Watching[/bold green] {memory_dir} (poll every {interval}s)")
    try:
        await watcher.start()
    except KeyboardInterrupt:
        watcher.stop()
        console.print("[dim]Watcher stopped.[/dim]")


@app.command()
def serve(
    port: int = typer.Option(18789, "--port", "-p", help="WebSocket port"),
    token_issuer: str = typer.Option(
        "http://client:3000/mcp-tokens", "--token-issuer", help="MCP token issuer URL",
    ),
    gateway: str = typer.Option(
        "http://mcp-gateway:3200/mcp", "--gateway", help="MCP gateway URL",
    ),
):
    """Start the WebSocket gateway server."""
    asyncio.run(_serve(port, token_issuer, gateway))


async def _serve(port: int, token_issuer: str, gateway_url: str):
    from app.gateway import Gateway
    gw = Gateway(port=port, token_issuer_url=token_issuer, gateway_url=gateway_url)
    await gw.start()


if __name__ == "__main__":
    app()
