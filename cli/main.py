import asyncio
from dataclasses import replace
import inspect
import logging
import os
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
from app.definitions import (
    DATA_DIR, LOG_DIR, SESSIONS_DIR, MEMORY_DOCS_DIR, WORKSPACE_DIR, AGENT_MODEL,
)
from app.logger import clear_logs
from app.session_export_hook import SessionExportHook
from app.session import SessionManager
from app.smol_rag import SmolRag, create_smol_rag
from app.tools.factory import build_tool_registry
from app.tools.memory_tools import MemoryRecallTool, MemoryStoreTool
from app.utilities import ensure_dir


def _get_param_metavar(param, ctx):
    try:
        return param.type.get_metavar(param=param, ctx=ctx)
    except TypeError:
        return param.type.get_metavar(param)


def _patch_typer_click_compat():
    # Typer 0.15.x still calls make_metavar() with the pre-Click 8.2 signature.
    if tuple(inspect.signature(typer.core.TyperArgument.make_metavar).parameters) == ("self",):
        def _argument_make_metavar(self, ctx=None):
            if self.metavar is not None:
                return self.metavar
            var = (self.name or "").upper()
            if not self.required:
                var = f"[{var}]"
            type_var = _get_param_metavar(self, ctx)
            if type_var:
                var += f":{type_var}"
            if self.nargs != 1:
                var += "..."
            return var

        typer.core.TyperArgument.make_metavar = _argument_make_metavar

    if tuple(inspect.signature(typer.core.TyperOption.make_metavar).parameters) == ("self", "ctx"):
        def _option_make_metavar(self, ctx=None):
            if self.metavar is not None:
                return self.metavar

            metavar = _get_param_metavar(self, ctx)
            if metavar is None:
                metavar = self.type.name.upper()
            if self.nargs != 1:
                metavar += "..."
            return metavar

        typer.core.TyperOption.make_metavar = _option_make_metavar


_patch_typer_click_compat()


app = typer.Typer(
    help="SmolClaw — agentic assistant with persistent memory",
    rich_markup_mode=None,
)
console = Console()

DEFAULT_AGENTS_CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.yaml")
SLASH_COMMANDS_HELP = "\n".join([
    "Slash commands:",
    "  / or /help or /commands  Show this command list",
    "  /remember <text>         Store a memory immediately",
    "  /remember-thread         Export the current chat thread to memory",
    "  /clear                   Clear the current chat session",
    "  /quit or /exit           Exit chat",
])


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


async def _close_async_resource(resource):
    close_fn = getattr(resource, "close", None)
    if not callable(close_fn):
        return
    result = close_fn()
    if inspect.isawaitable(result):
        await result


def _format_action_event(event: dict) -> str | None:
    if event.get("type") != "tool":
        return None

    name = event.get("name", "tool")
    if event.get("phase") == "start":
        summary = event.get("summary") or name
        return f"action: {summary}"

    if event.get("phase") == "end":
        duration_ms = max(0, int(event.get("duration_ms", 0)))
        duration_s = duration_ms / 1000
        if event.get("ok", True):
            return f"done: {name} ({duration_s:.1f}s)"
        result_preview = event.get("result_preview") or "Error"
        return f"failed: {name} ({duration_s:.1f}s) - {result_preview}"

    return None


def _build_cli_tool_registry(smol_rag: SmolRag, workspace: str, llm=None):
    return build_tool_registry(
        smol_rag=smol_rag,
        memory_docs_dir=MEMORY_DOCS_DIR,
        workspace=workspace,
        llm=llm,
        mode="direct",
    )


def _build_multiagent(
    agent_name: str,
    agents_config_path: str,
    session_key: str,
    smol_rag: SmolRag,
    workspace: str,
    session_manager: SessionManager,
    auto_export: bool,
) -> AgentLoop:
    from app.agent_config import AgentConfigLoader
    from app.agent_factory import build_agent_loop
    from app.subagent import SubagentManager
    from app.tools.spawn import SpawnTool, GetResultTool, AwaitResultTool
    from app.hooks import ON_SESSION_END

    configs = AgentConfigLoader.load(agents_config_path)
    if agent_name not in configs:
        available = ", ".join(sorted(configs.keys()))
        raise typer.BadParameter(f"Unknown agent '{agent_name}'. Available: {available}")

    master_registry = _build_cli_tool_registry(smol_rag, workspace)

    memory_dir = ensure_dir(MEMORY_DOCS_DIR) if auto_export else None

    def register_session_export(loop: AgentLoop):
        if not auto_export or memory_dir is None:
            return
        loop.hook_runner.on(
            ON_SESSION_END,
            SessionExportHook(
                smol_rag=smol_rag,
                llm=loop.llm,
                memory_dir=memory_dir,
            ),
        )

    subagent_manager = SubagentManager(
        configs=configs,
        master_registry=master_registry,
        smol_rag=smol_rag,
        session_manager=session_manager,
        session_end_hook_registrar=register_session_export if auto_export else None,
    )
    master_registry.register(SpawnTool(subagent_manager))
    master_registry.register(GetResultTool(subagent_manager))
    master_registry.register(AwaitResultTool(subagent_manager))

    agent = build_agent_loop(
        config=configs[agent_name],
        master_registry=master_registry,
        smol_rag=smol_rag,
        session_manager=session_manager,
        session_key_prefix=session_key,
    )
    agent.add_owned_resource(subagent_manager)
    return agent


def _build_default_chat_agent(
    agents_config_path: str,
    session_key: str,
    model: str,
    smol_rag: SmolRag,
    workspace: str,
    session_manager: SessionManager,
) -> AgentLoop:
    from app.agent_config import AgentConfigLoader
    from app.agent_factory import build_agent_loop

    configs = AgentConfigLoader.load(agents_config_path)
    if "default" not in configs:
        raise typer.BadParameter(
            f"Agents config '{agents_config_path}' must define a 'default' agent for chat."
        )

    config = replace(configs["default"], model=model)
    registry = _build_cli_tool_registry(smol_rag, workspace)
    return build_agent_loop(
        config=config,
        master_registry=registry,
        smol_rag=smol_rag,
        session_manager=session_manager,
        session_key=session_key,
    )


@app.command()
def chat(
    session_key: str = typer.Option("default", "--session", "-s", help="Session key"),
    workspace: str = typer.Option(WORKSPACE_DIR, "--workspace", "-w", help="Workspace directory"),
    model: str = typer.Option(AGENT_MODEL, "--model", "-m", help="LLM model to use"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name from agents.yaml"),
    agents_config: str = typer.Option(DEFAULT_AGENTS_CONFIG, "--agents-config", help="Path to agents YAML config"),
    auto_export: bool = typer.Option(True, "--auto-export/--no-auto-export", help="Auto-export session on close"),
    show_actions: bool = typer.Option(True, "--show-actions/--hide-actions", help="Show live tool activity while the agent works"),
):
    """Start an interactive chat session."""
    asyncio.run(_chat_loop(session_key, workspace, model, agent, agents_config, auto_export, show_actions))


async def _chat_loop(
    session_key: str,
    workspace: str,
    model: str,
    agent_name: Optional[str] = None,
    agents_config: str = DEFAULT_AGENTS_CONFIG,
    auto_export: bool = True,
    show_actions: bool = True,
):
    ensure_dir(SESSIONS_DIR)

    smol_rag = create_smol_rag()
    session_manager = SessionManager(SESSIONS_DIR)

    if agent_name:
        agent = _build_multiagent(
            agent_name, agents_config, session_key, smol_rag, workspace, session_manager, auto_export,
        )
        label = agent_name.capitalize()
    else:
        agent = _build_default_chat_agent(
            agents_config_path=agents_config,
            session_key=session_key,
            model=model,
            smol_rag=smol_rag,
            workspace=workspace,
            session_manager=session_manager,
        )
        label = "SmolClaw"

    memory_store_tool = MemoryStoreTool(
        smol_rag=smol_rag,
        memory_docs_dir=ensure_dir(MEMORY_DOCS_DIR),
        llm=agent.llm,
    )
    session_export_hook = SessionExportHook(
        smol_rag=smol_rag,
        llm=agent.llm,
        memory_dir=ensure_dir(MEMORY_DOCS_DIR),
    )

    if auto_export:
        from app.hooks import ON_SESSION_END
        from app.lifecycle_hooks import MemoryDecayHook, ContradictionExpiryHook

        agent.hook_runner.on(
            ON_SESSION_END,
            session_export_hook,
        )
        agent.hook_runner.on(ON_SESSION_END, MemoryDecayHook(smol_rag))
        if hasattr(smol_rag, 'contradiction_detector') and smol_rag.contradiction_detector:
            agent.hook_runner.on(
                ON_SESSION_END,
                ContradictionExpiryHook(smol_rag.contradiction_detector),
            )

    history_file = os.path.join(SESSIONS_DIR, "prompt_history.txt")
    prompt_session = PromptSession(history=FileHistory(history_file))

    console.print(f"[bold green]{label}[/bold green] ready. Type /help for commands, /quit to exit.\n")

    try:
        while True:
            try:
                user_input = await prompt_session.prompt_async("you> ")
            except (EOFError, KeyboardInterrupt):
                break

            user_input = user_input.strip()
            if not user_input:
                continue
            command_parts = user_input.split(maxsplit=1)
            command = command_parts[0]
            command_arg = command_parts[1].strip() if len(command_parts) > 1 else ""
            if command in ("/", "/help", "/commands"):
                console.print(f"[dim]{SLASH_COMMANDS_HELP}[/dim]")
                continue
            if user_input in ("/quit", "/exit"):
                break
            if user_input == "/clear":
                agent.session.clear()
                session_manager.save(agent.session)
                console.print("[dim]Session cleared.[/dim]")
                continue
            if command == "/remember":
                if not command_arg:
                    console.print("[dim]Usage: /remember <text>[/dim]")
                    continue
                with console.status("[bold cyan]storing memory...[/bold cyan]"):
                    result = await memory_store_tool.execute(content=command_arg)
                console.print(f"[dim]{result}[/dim]")
                continue
            if command == "/remember-thread":
                with console.status("[bold cyan]remembering current thread...[/bold cyan]"):
                    await session_export_hook({
                        "session_key": agent.session.key,
                        "session": agent.session,
                    })
                console.print("[dim]Current thread exported to memory.[/dim]")
                continue

            async def on_event(event: dict):
                if not show_actions:
                    return
                line = _format_action_event(event)
                if line:
                    console.print(f"[dim]{line}[/dim]")

            if show_actions:
                response = await agent.process(user_input, on_event=on_event)
            else:
                with console.status("[bold cyan]thinking...[/bold cyan]"):
                    response = await agent.process(user_input)

            console.print()
            console.print(Markdown(response))
            console.print()
    finally:
        try:
            if auto_export:
                with console.status("[bold cyan]exporting session...[/bold cyan]"):
                    await agent.close()
                console.print("[dim]Session exported.[/dim]")
            else:
                await agent.close()
        finally:
            await _close_async_resource(smol_rag)


@app.command()
def ingest(
    path: str = typer.Argument(..., help="File or directory to ingest"),
):
    """Ingest documents into memory."""
    asyncio.run(_ingest(path))


async def _ingest(path: str):
    from app.utilities import get_docs, make_hash
    smol_rag = create_smol_rag()
    try:
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
    finally:
        await _close_async_resource(smol_rag)


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
    smol_rag = create_smol_rag()
    watcher = MemoryFileWatcher(memory_dir, smol_rag, poll_interval=interval)
    console.print(f"[bold green]Watching[/bold green] {memory_dir} (poll every {interval}s)")
    try:
        await watcher.start()
    except KeyboardInterrupt:
        watcher.stop()
        console.print("[dim]Watcher stopped.[/dim]")
    finally:
        await _close_async_resource(smol_rag)


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


@app.command()
def recall(
    query: str = typer.Argument(..., help="Search query for past sessions"),
    mode: str = typer.Option("topic", "--mode", "-m", help="Search mode: topic or temporal"),
    days: float = typer.Option(7, "--days", "-d", help="For temporal mode: how many days back"),
):
    """Search past sessions using BM25 + semantic search."""
    asyncio.run(_recall(query, mode, days))


async def _recall(query: str, mode: str, days: float):
    smol_rag = create_smol_rag()
    try:
        tool = MemoryRecallTool(smol_rag)
        result = await tool.execute(query=query, mode=mode, days=days)
        console.print(Markdown(result))
    finally:
        await _close_async_resource(smol_rag)


@app.command(name="index-sessions")
def index_sessions(
    sessions_dir: str = typer.Option(SESSIONS_DIR, "--sessions-dir", help="Sessions directory"),
    memory_dir: str = typer.Option(MEMORY_DOCS_DIR, "--memory-dir", help="Memory docs directory"),
):
    """Index all past sessions into SmolRAG for recall."""
    asyncio.run(_index_sessions(sessions_dir, memory_dir))


async def _index_sessions(sessions_dir: str, memory_dir: str):
    from app.session_indexer import index_all_sessions
    smol_rag = create_smol_rag()
    try:
        results = await index_all_sessions(sessions_dir, smol_rag, memory_dir=memory_dir)
        for key, source_id in results.items():
            console.print(f"[green]Indexed:[/green] {key} -> {source_id}")
        console.print(f"\n[bold]Done:[/bold] {len(results)} sessions indexed")
    finally:
        await _close_async_resource(smol_rag)


@app.command()
def reset(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Wipe all persistent data (memories, sessions, indexes) for a full reset."""
    if not force:
        confirm = typer.confirm(
            "This will delete all memories, sessions, and indexes. Continue?"
        )
        if not confirm:
            raise typer.Abort()
    asyncio.run(_reset())


async def _reset():
    from app.reset import reset_all_stores
    deleted = await reset_all_stores(DATA_DIR)
    if deleted:
        for line in deleted:
            console.print(f"  [red]{line}[/red]")
        console.print(f"\n[bold]Reset complete.[/bold] {len(deleted)} action(s).")
    else:
        console.print("[dim]Nothing to reset — stores already clean.[/dim]")


@app.command(name="clear-logs")
def clear_logs_command(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    logs_dir: str = typer.Option(LOG_DIR, "--logs-dir", help="Logs directory"),
):
    """Delete log files without touching memories, sessions, or indexes."""
    if not force:
        confirm = typer.confirm(
            f"This will delete log files under '{logs_dir}'. Continue?"
        )
        if not confirm:
            raise typer.Abort()

    deleted = clear_logs(logs_dir)
    if deleted:
        for path in deleted:
            console.print(f"  [red]Deleted {path}[/red]")
        console.print(f"\n[bold]Log cleanup complete.[/bold] {len(deleted)} file(s) removed.")
    else:
        console.print("[dim]No log files to delete.[/dim]")


if __name__ == "__main__":
    app()
