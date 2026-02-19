import asyncio
import os
import re
import signal
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

from app.agent_config import AgentConfig, AgentConfigLoader
from app.agent_factory import build_agent_loop
from app.logger import logger
from app.session import SessionManager
from app.tools.registry import ToolRegistry

console = Console()


class ArticleStatus(Enum):
    pending = "pending"
    researching = "researching"
    planning = "planning"
    writing = "writing"
    critiquing = "critiquing"
    revising = "revising"
    completed = "completed"
    failed = "failed"
    skip = "skip"


@dataclass
class ArticleBrief:
    title: str
    content_type: str
    slug: str
    status: ArticleStatus = ArticleStatus.pending
    error: Optional[str] = None
    source: str = "calendar"


@dataclass
class PipelineResult:
    brief: ArticleBrief
    success: bool
    duration: float = 0.0
    error: Optional[str] = None


def title_to_slug(title: str) -> str:
    """Convert a title to a kebab-case slug.

    Takes the part before the first colon (matching existing convention),
    strips quotes, lowercases, and replaces non-alphanumeric chars with hyphens.
    """
    # Take part before first colon
    slug = title.split(":")[0].strip()
    # Strip quotes
    slug = slug.replace('"', "").replace("'", "").replace("\u201c", "").replace("\u201d", "")
    # Lowercase
    slug = slug.lower()
    # Replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    return slug


def parse_content_calendar(calendar_path: str) -> List[ArticleBrief]:
    """Parse the content calendar markdown and extract article briefs."""
    with open(calendar_path) as f:
        content = f.read()

    briefs = []
    current_week = None

    for line in content.split("\n"):
        # Track current week
        week_match = re.match(r"^### Week (\d+)", line)
        if week_match:
            current_week = int(week_match.group(1))
            continue
        # Reset on non-week headings (summary tables at end of calendar)
        if re.match(r"^#{2,3}\s", line) and not week_match:
            current_week = None
            continue

        # Parse table rows (skip header and separator rows)
        if not line.startswith("|") or current_week is None:
            continue
        cells = [c.strip() for c in line.split("|")]
        # Filter empty strings from split
        cells = [c for c in cells if c]
        if len(cells) < 3:
            continue
        # Skip header rows
        if cells[0] in ("Day", "---", "") or cells[0].startswith("-"):
            continue

        day = cells[0]
        title = cells[1]
        content_type = cells[2]

        # Skip separator rows
        if set(day.replace("-", "")) == set() or set(title.replace("-", "")) == set():
            continue

        slug = title_to_slug(title)
        briefs.append(ArticleBrief(
            title=title,
            content_type=content_type,
            slug=slug,
            source="calendar",
        ))

    return briefs


def _normalize_for_match(text: str) -> str:
    """Normalize text for fuzzy matching: lowercase, strip punctuation."""
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def find_unwritten_articles(briefs: List[ArticleBrief], posts_dir: str) -> List[ArticleBrief]:
    """Filter briefs to only those not yet written, checking both filenames and frontmatter titles."""
    if not os.path.isdir(posts_dir):
        return briefs

    existing_slugs = set()
    existing_titles = set()

    for fname in os.listdir(posts_dir):
        if not fname.endswith(".md"):
            continue
        slug = fname[:-3]  # Strip .md
        existing_slugs.add(slug)

        # Also read frontmatter title
        fpath = os.path.join(posts_dir, fname)
        try:
            with open(fpath) as f:
                for line in f:
                    line = line.strip()
                    if line == "---":
                        continue
                    if line.startswith("title:"):
                        title_val = line[len("title:"):].strip().strip("'\"")
                        existing_titles.add(_normalize_for_match(title_val))
                        break
                    if line and not line.startswith(("---", "title:")):
                        break
        except (OSError, UnicodeDecodeError):
            pass

    unwritten = []
    for brief in briefs:
        if brief.slug in existing_slugs:
            continue
        if _normalize_for_match(brief.title) in existing_titles:
            continue
        unwritten.append(brief)
    return unwritten


def _parse_ideator_output(output: str) -> List[str]:
    """Extract article titles from ideator output (## heading lines)."""
    titles = []
    for line in output.split("\n"):
        match = re.match(r"^##\s+(.+)", line)
        if match:
            title = match.group(1).strip()
            # Ignore very short headings (likely section labels)
            if len(title) > 10:
                titles.append(title)
    return titles


QUEUE_HEADER = "| Status | Title | Content Type | Source | Slug |"
QUEUE_SEPARATOR = "|--------|-------|-------------|--------|------|"


def _load_queue_file(queue_path: str) -> List[ArticleBrief]:
    """Load article queue from markdown file."""
    if not os.path.exists(queue_path):
        return []

    briefs = []
    with open(queue_path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.split("|")]
            cells = [c for c in cells if c]
            if len(cells) < 5:
                continue
            status_str, title, content_type, source, slug = cells[0], cells[1], cells[2], cells[3], cells[4]
            # Skip header/separator
            if status_str in ("Status", "---", "") or status_str.startswith("-"):
                continue
            try:
                status = ArticleStatus(status_str)
            except ValueError:
                # Treat unknown statuses (like "skip") as skip
                status = ArticleStatus.skip
            briefs.append(ArticleBrief(
                title=title,
                content_type=content_type,
                slug=slug,
                status=status,
                source=source,
            ))
    return briefs


def _write_queue_file(queue_path: str, briefs: List[ArticleBrief]):
    """Write article queue to markdown file."""
    os.makedirs(os.path.dirname(queue_path), exist_ok=True)
    lines = [
        "# Article Queue\n",
        "",
        QUEUE_HEADER,
        QUEUE_SEPARATOR,
    ]
    for b in briefs:
        lines.append(f"| {b.status.value} | {b.title} | {b.content_type} | {b.source} | {b.slug} |")
    lines.append("")

    with open(queue_path, "w") as f:
        f.write("\n".join(lines))


class Autopilot:
    def __init__(
        self,
        configs: Dict[str, AgentConfig],
        tool_registry: ToolRegistry,
        smol_rag,
        session_manager: SessionManager,
        calendar_path: str,
        posts_dir: str,
        queue_path: str,
        pause_seconds: int = 30,
        ideator_interval: int = 5,
    ):
        self.configs = configs
        self.tool_registry = tool_registry
        self.smol_rag = smol_rag
        self.session_manager = session_manager
        self.calendar_path = calendar_path
        self.posts_dir = posts_dir
        self.queue_path = queue_path
        self.pause_seconds = pause_seconds
        self.ideator_interval = ideator_interval

        self._shutdown_requested = False
        self._force_shutdown = False
        self._results: List[PipelineResult] = []

    async def run(self):
        """Main autopilot loop."""
        # Set up signal handling
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        try:
            await self._run_inner()
        finally:
            # Clean up signal handlers
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)

    async def _run_inner(self):
        # Load or build queue
        queue = self._load_or_build_queue()
        pending = [b for b in queue if b.status == ArticleStatus.pending]

        if not pending:
            console.print("[yellow]No pending articles in queue. Running ideator for new topics...[/yellow]")
            await self._run_ideator(queue)
            _write_queue_file(self.queue_path, queue)
            pending = [b for b in queue if b.status == ArticleStatus.pending]

        if not pending:
            console.print("[yellow]No articles to process after ideator run.[/yellow]")
            self._print_summary()
            return

        console.print(f"[bold green]Autopilot starting:[/bold green] {len(pending)} articles to process")

        articles_since_ideator = 0

        for brief in pending:
            if self._shutdown_requested:
                console.print("[yellow]Shutdown requested — stopping after current article.[/yellow]")
                break

            articles_since_ideator += 1
            console.print(f"\n[bold cyan]>>> Processing:[/bold cyan] {brief.title}")

            result = await self._run_pipeline(brief)
            self._results.append(result)

            # Update queue file after each article
            _write_queue_file(self.queue_path, queue)

            if result.success:
                console.print(f"[green]Completed:[/green] {brief.title} ({result.duration:.0f}s)")
            else:
                console.print(f"[red]Failed:[/red] {brief.title} — {result.error}")

            # Run ideator periodically
            if articles_since_ideator >= self.ideator_interval and not self._shutdown_requested:
                console.print("\n[dim]Running ideator for new topics...[/dim]")
                await self._run_ideator(queue)
                _write_queue_file(self.queue_path, queue)
                articles_since_ideator = 0

            # Pause between articles
            if not self._shutdown_requested:
                console.print(f"[dim]Pausing {self.pause_seconds}s before next article...[/dim]")
                await asyncio.sleep(self.pause_seconds)

        self._print_summary()

    def _load_or_build_queue(self) -> List[ArticleBrief]:
        """Load existing queue file or build from calendar + filesystem scan."""
        existing_queue = _load_queue_file(self.queue_path)
        if existing_queue:
            console.print(f"[dim]Loaded queue from {self.queue_path} ({len(existing_queue)} articles)[/dim]")
            return existing_queue

        # Build from calendar
        calendar_briefs = parse_content_calendar(self.calendar_path)
        console.print(f"[dim]Parsed {len(calendar_briefs)} articles from content calendar[/dim]")

        # Check which already exist
        existing_slugs = set()
        existing_titles = set()
        if os.path.isdir(self.posts_dir):
            for fname in os.listdir(self.posts_dir):
                if fname.endswith(".md"):
                    existing_slugs.add(fname[:-3])
                    fpath = os.path.join(self.posts_dir, fname)
                    try:
                        with open(fpath) as f:
                            for line in f:
                                line = line.strip()
                                if line == "---":
                                    continue
                                if line.startswith("title:"):
                                    title_val = line[len("title:"):].strip().strip("'\"")
                                    existing_titles.add(_normalize_for_match(title_val))
                                    break
                                if line and not line.startswith(("---", "title:")):
                                    break
                    except (OSError, UnicodeDecodeError):
                        pass

        for brief in calendar_briefs:
            if brief.slug in existing_slugs or _normalize_for_match(brief.title) in existing_titles:
                brief.status = ArticleStatus.completed
            else:
                brief.status = ArticleStatus.pending

        _write_queue_file(self.queue_path, calendar_briefs)
        completed = sum(1 for b in calendar_briefs if b.status == ArticleStatus.completed)
        pending = sum(1 for b in calendar_briefs if b.status == ArticleStatus.pending)
        console.print(f"[dim]Built queue: {completed} completed, {pending} pending[/dim]")
        return calendar_briefs

    async def _run_pipeline(self, brief: ArticleBrief) -> PipelineResult:
        """Run the researcher → planner → writer pipeline for a single article."""
        start = time.time()
        session_prefix = f"autopilot-{brief.slug}"

        stages = [
            ("researcher", ArticleStatus.researching, 600,
             f"Research the topic: '{brief.title}' ({brief.content_type}). "
             f"Find authoritative sources, data, and expert analysis. "
             f"Store all findings in memory with source attribution."),
            ("planner", ArticleStatus.planning, 300,
             f"Create an article outline for: '{brief.title}' ({brief.content_type}). "
             f"Search memory for the research the researcher agent stored. "
             f"Follow the article template exactly. "
             f"Save the outline to vault/articles/content-outlines/{brief.slug}.md"),
            ("writer", ArticleStatus.writing, 600,
             f"Write the article: '{brief.title}' ({brief.content_type}). "
             f"Read the outline from vault/articles/content-outlines/{brief.slug}.md. "
             f"Search memory for research. Follow the style guide. "
             f"Save the finished article to vault/articles/posts/{brief.slug}.md"),
            ("critic", ArticleStatus.critiquing, 300,
             f"Review the article '{brief.title}'. "
             f"Read it from vault/articles/posts/{brief.slug}.md. "
             f"Check against your detection rules in agents/critic.md and "
             f"the style guide in agents/write-marketing-content.md. "
             f"Produce a severity-ranked critique report. "
             f"Save to vault/articles/critiques/{brief.slug}-critique.md"),
            ("writer", ArticleStatus.revising, 600,
             f"Revise the article '{brief.title}'. "
             f"Read the critique from vault/articles/critiques/{brief.slug}-critique.md. "
             f"Read your article from vault/articles/posts/{brief.slug}.md. "
             f"Address every Critical and Major issue in the critique. "
             f"Rewrite flagged passages to eliminate AI-generated content markers. "
             f"Save the revised article back to vault/articles/posts/{brief.slug}.md"),
        ]

        for agent_name, status, timeout, prompt in stages:
            if self._shutdown_requested:
                brief.status = ArticleStatus.failed
                brief.error = "Shutdown requested"
                return PipelineResult(brief=brief, success=False,
                                      duration=time.time() - start, error="Shutdown requested")

            brief.status = status
            console.print(f"  [dim]{status.value}...[/dim]")

            try:
                agent_loop = build_agent_loop(
                    config=self.configs[agent_name],
                    master_registry=self.tool_registry,
                    smol_rag=self.smol_rag,
                    session_manager=self.session_manager,
                    session_key_prefix=session_prefix,
                )
                await asyncio.wait_for(agent_loop.process(prompt), timeout=timeout)
            except asyncio.TimeoutError:
                brief.status = ArticleStatus.failed
                brief.error = f"Timeout during {agent_name} ({timeout}s)"
                return PipelineResult(brief=brief, success=False,
                                      duration=time.time() - start,
                                      error=brief.error)
            except Exception as e:
                brief.status = ArticleStatus.failed
                brief.error = f"Error in {agent_name}: {e}"
                logger.error(f"Pipeline error for '{brief.title}': {e}")
                return PipelineResult(brief=brief, success=False,
                                      duration=time.time() - start,
                                      error=brief.error)

        brief.status = ArticleStatus.completed
        brief.error = None

        try:
            await self._ingest_article(brief)
        except Exception as e:
            logger.warning(f"RAG ingestion failed for '{brief.title}': {e}")

        return PipelineResult(brief=brief, success=True, duration=time.time() - start)

    async def _ingest_article(self, brief: ArticleBrief):
        """Ingest a completed article into the RAG for future agent queries."""
        article_path = os.path.join(self.posts_dir, f"{brief.slug}.md")
        if not os.path.exists(article_path):
            logger.warning(f"Article file not found for ingestion: {article_path}")
            return

        with open(article_path) as f:
            content = f.read()

        source_id = f"article-{brief.slug}"
        await self.smol_rag.ingest_text(content, source_id=source_id)
        console.print(f"  [dim]ingested into RAG[/dim]")

    async def _run_ideator(self, queue: List[ArticleBrief]):
        """Run ideator agent to discover new topics and append to queue."""
        session_prefix = f"autopilot-ideator-{int(time.time())}"

        try:
            agent_loop = build_agent_loop(
                config=self.configs["ideator"],
                master_registry=self.tool_registry,
                smol_rag=self.smol_rag,
                session_manager=self.session_manager,
                session_key_prefix=session_prefix,
            )
            output = await asyncio.wait_for(
                agent_loop.process(
                    "Survey the content landscape: read the content calendar, existing outlines, "
                    "and published posts. Search memory for recent research. Then generate new "
                    "article ideas that fill gaps. Format each idea as a ## heading with the "
                    "working title, followed by a brief description."
                ),
                timeout=600,
            )
        except (asyncio.TimeoutError, Exception) as e:
            console.print(f"[red]Ideator failed: {e}[/red]")
            return

        new_titles = _parse_ideator_output(output)
        if not new_titles:
            console.print("[dim]Ideator produced no new topics.[/dim]")
            return

        # Deduplicate against existing queue and posts
        existing_slugs = {b.slug for b in queue}
        if os.path.isdir(self.posts_dir):
            for fname in os.listdir(self.posts_dir):
                if fname.endswith(".md"):
                    existing_slugs.add(fname[:-3])

        added = 0
        for title in new_titles:
            slug = title_to_slug(title)
            if slug in existing_slugs:
                continue
            existing_slugs.add(slug)
            queue.append(ArticleBrief(
                title=title,
                content_type="Ideator Suggestion",
                slug=slug,
                status=ArticleStatus.pending,
                source="ideator",
            ))
            added += 1

        console.print(f"[green]Ideator added {added} new topics to queue.[/green]")

    def _handle_signal(self):
        """Handle Ctrl+C: first press = graceful shutdown, second = force exit."""
        if self._shutdown_requested:
            console.print("\n[red]Force shutdown.[/red]")
            self._force_shutdown = True
            raise SystemExit(1)
        console.print("\n[yellow]Shutdown requested — finishing current article...[/yellow]")
        self._shutdown_requested = True

    def _print_summary(self):
        """Print a Rich summary table of results."""
        if not self._results:
            console.print("[dim]No articles processed.[/dim]")
            return

        table = Table(title="Autopilot Summary")
        table.add_column("Title", style="cyan", max_width=50)
        table.add_column("Status", justify="center")
        table.add_column("Duration", justify="right")
        table.add_column("Error", style="red", max_width=40)

        for r in self._results:
            status_style = "green" if r.success else "red"
            table.add_row(
                r.brief.title,
                f"[{status_style}]{r.brief.status.value}[/{status_style}]",
                f"{r.duration:.0f}s",
                r.error or "",
            )

        console.print()
        console.print(table)

        succeeded = sum(1 for r in self._results if r.success)
        failed = sum(1 for r in self._results if not r.success)
        console.print(f"\n[bold]Total:[/bold] {succeeded} completed, {failed} failed")
