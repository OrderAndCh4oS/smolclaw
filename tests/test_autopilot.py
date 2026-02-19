import asyncio
import os
import tempfile
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.autopilot import (
    ArticleBrief,
    ArticleStatus,
    Autopilot,
    PipelineResult,
    _load_queue_file,
    _normalize_for_match,
    _parse_ideator_output,
    _write_queue_file,
    find_unwritten_articles,
    parse_content_calendar,
    title_to_slug,
)


# ---------------------------------------------------------------------------
# title_to_slug
# ---------------------------------------------------------------------------

class TestTitleToSlug:
    def test_simple(self):
        assert title_to_slug("Team Subscriptions") == "team-subscriptions"

    def test_with_colon(self):
        assert title_to_slug("Your First Subscription Product: From Zero to Revenue") == "your-first-subscription-product"

    def test_with_quotes(self):
        assert title_to_slug('The Hidden Cost of "Simple" Pricing') == "the-hidden-cost-of-simple-pricing"

    def test_special_chars(self):
        assert title_to_slug("The $5-15 Sweet Spot") == "the-5-15-sweet-spot"

    def test_smart_quotes(self):
        assert title_to_slug("The \u201cBig\u201d Idea") == "the-big-idea"


# ---------------------------------------------------------------------------
# parse_content_calendar
# ---------------------------------------------------------------------------

class TestParseContentCalendar:
    @pytest.fixture
    def calendar_file(self, tmp_path):
        content = """# Content Calendar

### Week 1

| Day | Article | Content Type |
| --- | ------- | ------------ |
| Tuesday | Your First Subscription Product: From Zero | SaaS Startup Guide |
| Thursday | Introducing Tiered Pricing: Volume Discounts | Beta Feature |

### Week 2

| Day | Article | Content Type |
| --- | ------- | ------------ |
| Tuesday | Choosing Your First Pricing Model: Flat-Rate | SaaS Startup Guide |
"""
        path = tmp_path / "calendar.md"
        path.write_text(content)
        return str(path)

    def test_parses_articles(self, calendar_file):
        briefs = parse_content_calendar(calendar_file)
        assert len(briefs) == 3

    def test_extracts_titles(self, calendar_file):
        briefs = parse_content_calendar(calendar_file)
        assert briefs[0].title == "Your First Subscription Product: From Zero"
        assert briefs[1].title == "Introducing Tiered Pricing: Volume Discounts"

    def test_extracts_content_type(self, calendar_file):
        briefs = parse_content_calendar(calendar_file)
        assert briefs[0].content_type == "SaaS Startup Guide"
        assert briefs[1].content_type == "Beta Feature"

    def test_generates_slugs(self, calendar_file):
        briefs = parse_content_calendar(calendar_file)
        assert briefs[0].slug == "your-first-subscription-product"
        assert briefs[1].slug == "introducing-tiered-pricing"

    def test_skips_header_rows(self, calendar_file):
        briefs = parse_content_calendar(calendar_file)
        # Should not include "Day" or separator rows
        for b in briefs:
            assert b.title != "Day"
            assert "---" not in b.title

    def test_parses_real_calendar(self):
        """Parse the actual content calendar to verify against real data."""
        calendar_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "vault", "articles", "content-calendar.md",
        )
        if not os.path.exists(calendar_path):
            pytest.skip("Content calendar not found")
        briefs = parse_content_calendar(calendar_path)
        assert len(briefs) == 34


# ---------------------------------------------------------------------------
# find_unwritten_articles
# ---------------------------------------------------------------------------

class TestFindUnwrittenArticles:
    @pytest.fixture
    def posts_dir(self, tmp_path):
        d = tmp_path / "posts"
        d.mkdir()
        # Create a few existing posts
        (d / "team-subscriptions.md").write_text(
            "---\ntitle: 'Team Subscriptions: When One Seat Isn't Enough'\n---\nContent"
        )
        (d / "tiered-pricing.md").write_text(
            "---\ntitle: 'Introducing Tiered Pricing'\n---\nContent"
        )
        return str(d)

    def test_filters_by_slug(self, posts_dir):
        briefs = [
            ArticleBrief(title="Team Subscriptions: Test", content_type="Guide", slug="team-subscriptions"),
            ArticleBrief(title="New Article", content_type="Guide", slug="new-article"),
        ]
        result = find_unwritten_articles(briefs, posts_dir)
        assert len(result) == 1
        assert result[0].slug == "new-article"

    def test_filters_by_title(self, posts_dir):
        briefs = [
            ArticleBrief(title="Introducing Tiered Pricing", content_type="Beta", slug="introducing-tiered-pricing-extended"),
        ]
        result = find_unwritten_articles(briefs, posts_dir)
        assert len(result) == 0

    def test_keeps_unwritten(self, posts_dir):
        briefs = [
            ArticleBrief(title="Brand New Topic", content_type="Guide", slug="brand-new-topic"),
            ArticleBrief(title="Another New Topic", content_type="Guide", slug="another-new-topic"),
        ]
        result = find_unwritten_articles(briefs, posts_dir)
        assert len(result) == 2

    def test_handles_missing_dir(self):
        briefs = [ArticleBrief(title="Test", content_type="Guide", slug="test")]
        result = find_unwritten_articles(briefs, "/nonexistent/dir")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _parse_ideator_output
# ---------------------------------------------------------------------------

class TestParseIdeatorOutput:
    def test_extracts_headings(self):
        output = """Here are some ideas:

## The Psychology of Pricing Anchors in SaaS
This explores how anchoring affects conversion.

## Why Enterprise Customers Need Custom Billing Workflows
Enterprise billing is complex.

Some other text.
"""
        titles = _parse_ideator_output(output)
        assert len(titles) == 2
        assert titles[0] == "The Psychology of Pricing Anchors in SaaS"

    def test_ignores_short_headings(self):
        output = "## Ideas\n\n## The Real Topic Is Longer Than Ten Characters\n"
        titles = _parse_ideator_output(output)
        assert len(titles) == 1

    def test_deduplicates_not_here(self):
        """Deduplication is handled by _run_ideator, not by the parser."""
        output = "## Same Title Appears Twice Here\n## Same Title Appears Twice Here\n"
        titles = _parse_ideator_output(output)
        assert len(titles) == 2  # Parser returns all, dedup is separate


# ---------------------------------------------------------------------------
# Queue file I/O
# ---------------------------------------------------------------------------

class TestQueueFile:
    @pytest.fixture
    def queue_path(self, tmp_path):
        return str(tmp_path / "article-queue.md")

    def test_write_and_read_roundtrip(self, queue_path):
        briefs = [
            ArticleBrief(title="Article One", content_type="Guide", slug="article-one",
                         status=ArticleStatus.completed, source="calendar"),
            ArticleBrief(title="Article Two", content_type="Beta Feature", slug="article-two",
                         status=ArticleStatus.pending, source="ideator"),
        ]
        _write_queue_file(queue_path, briefs)
        loaded = _load_queue_file(queue_path)
        assert len(loaded) == 2
        assert loaded[0].title == "Article One"
        assert loaded[0].status == ArticleStatus.completed
        assert loaded[0].source == "calendar"
        assert loaded[1].title == "Article Two"
        assert loaded[1].status == ArticleStatus.pending
        assert loaded[1].source == "ideator"

    def test_load_nonexistent(self, tmp_path):
        result = _load_queue_file(str(tmp_path / "nope.md"))
        assert result == []

    def test_skip_status_preserved(self, queue_path):
        briefs = [
            ArticleBrief(title="Skipped", content_type="Guide", slug="skipped",
                         status=ArticleStatus.skip, source="calendar"),
        ]
        _write_queue_file(queue_path, briefs)
        loaded = _load_queue_file(queue_path)
        assert len(loaded) == 1
        assert loaded[0].status == ArticleStatus.skip

    def test_failed_status_preserved(self, queue_path):
        briefs = [
            ArticleBrief(title="Failed", content_type="Guide", slug="failed",
                         status=ArticleStatus.failed, source="calendar"),
        ]
        _write_queue_file(queue_path, briefs)
        loaded = _load_queue_file(queue_path)
        assert loaded[0].status == ArticleStatus.failed


# ---------------------------------------------------------------------------
# Autopilot pipeline (mocked agents)
# ---------------------------------------------------------------------------

class TestAutopilotPipeline:
    @pytest.fixture
    def setup(self, tmp_path):
        """Set up mocked Autopilot with temp dirs."""
        posts_dir = tmp_path / "posts"
        posts_dir.mkdir()
        queue_path = str(tmp_path / "article-queue.md")
        calendar_path = str(tmp_path / "calendar.md")
        sessions_dir = str(tmp_path / "sessions")
        os.makedirs(sessions_dir)

        # Write a minimal calendar
        (tmp_path / "calendar.md").write_text("""# Calendar

### Week 1

| Day | Article | Content Type |
| --- | ------- | ------------ |
| Tuesday | Test Article One: Subtitle | Guide |
| Thursday | Test Article Two: Another | Feature |
""")

        # Mock configs for required agents
        from app.agent_config import AgentConfig
        configs = {
            name: AgentConfig(name=name, model="gpt-4.1", persona=f"{name} persona", tools=[])
            for name in ["researcher", "planner", "writer", "critic", "ideator"]
        }

        mock_smol_rag = MagicMock()
        mock_smol_rag.mix_query = AsyncMock(return_value="Mock result")
        mock_smol_rag.ingest_text = AsyncMock()

        from app.session import SessionManager
        session_manager = SessionManager(sessions_dir)

        registry = MagicMock()

        pilot = Autopilot(
            configs=configs,
            tool_registry=registry,
            smol_rag=mock_smol_rag,
            session_manager=session_manager,
            calendar_path=calendar_path,
            posts_dir=str(posts_dir),
            queue_path=queue_path,
            pause_seconds=0,
            ideator_interval=100,  # Don't trigger ideator during tests
        )

        return pilot, posts_dir, queue_path

    @pytest.mark.asyncio
    async def test_pipeline_five_stages(self, setup):
        """Pipeline calls researcher, planner, writer, critic, writer(revision) in sequence."""
        pilot, posts_dir, queue_path = setup

        calls = []

        async def mock_process(prompt):
            calls.append(prompt)
            return "Done"

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=mock_process)

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            brief = ArticleBrief(title="Test", content_type="Guide", slug="test")
            result = await pilot._run_pipeline(brief)

        assert result.success
        assert brief.status == ArticleStatus.completed
        assert len(calls) == 5
        assert "Research" in calls[0]
        assert "outline" in calls[1].lower()
        assert "Write" in calls[2]
        assert "Review" in calls[3]
        assert "Revise" in calls[4]

    @pytest.mark.asyncio
    async def test_pipeline_handles_failure(self, setup):
        """If a stage fails, pipeline marks brief as failed and stops."""
        pilot, posts_dir, queue_path = setup

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            brief = ArticleBrief(title="Fail Test", content_type="Guide", slug="fail-test")
            result = await pilot._run_pipeline(brief)

        assert not result.success
        assert brief.status == ArticleStatus.failed
        assert "researcher" in brief.error

    @pytest.mark.asyncio
    async def test_pipeline_continues_after_failure(self, setup):
        """Autopilot continues to next article after a failure."""
        pilot, posts_dir, queue_path = setup

        call_count = 0

        async def mock_process(prompt):
            nonlocal call_count
            call_count += 1
            if call_count <= 5:  # First article (5 stages) succeeds
                return "Done"
            if call_count == 6:  # Second article's researcher fails
                raise Exception("Boom")
            return "Done"

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=mock_process)

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            # Queue has 2 articles from the calendar fixture
            await pilot._run_inner()

        # Should have processed both articles (first succeeds, second fails at researcher)
        assert len(pilot._results) == 2
        assert pilot._results[0].success
        assert not pilot._results[1].success

    @pytest.mark.asyncio
    async def test_shutdown_stops_loop(self, setup):
        """Setting _shutdown_requested stops after current article."""
        pilot, posts_dir, queue_path = setup

        async def mock_process(prompt):
            # Request shutdown after first article's first stage
            pilot._shutdown_requested = True
            return "Done"

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=mock_process)

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            brief = ArticleBrief(title="Shutdown Test", content_type="Guide", slug="shutdown-test")
            result = await pilot._run_pipeline(brief)

        # Pipeline should have stopped early due to shutdown
        assert not result.success
        assert "Shutdown" in result.error

    @pytest.mark.asyncio
    async def test_queue_file_updated_after_pipeline(self, setup):
        """Queue file is written after each article completes."""
        pilot, posts_dir, queue_path = setup

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="Done")

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            await pilot._run_inner()

        # Queue file should exist and have entries
        loaded = _load_queue_file(queue_path)
        assert len(loaded) == 2
        assert all(b.status == ArticleStatus.completed for b in loaded)

    @pytest.mark.asyncio
    async def test_load_existing_queue(self, setup):
        """If queue file exists, load it instead of rebuilding from calendar."""
        pilot, posts_dir, queue_path = setup

        # Pre-write a queue with one completed and one pending
        _write_queue_file(queue_path, [
            ArticleBrief(title="Already Done", content_type="Guide", slug="already-done",
                         status=ArticleStatus.completed, source="calendar"),
            ArticleBrief(title="Still Pending", content_type="Guide", slug="still-pending",
                         status=ArticleStatus.pending, source="calendar"),
        ])

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="Done")

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            await pilot._run_inner()

        # Should have only processed the pending one
        assert len(pilot._results) == 1
        assert pilot._results[0].brief.slug == "still-pending"

    @pytest.mark.asyncio
    async def test_pipeline_ingests_article_on_success(self, setup):
        """After a successful pipeline run, the finished article is ingested into the RAG."""
        pilot, posts_dir, queue_path = setup

        # Write a dummy article file that the pipeline would have produced
        article_content = "---\ntitle: 'Test Article'\n---\n\nHello world."
        (posts_dir / "test-ingest.md").write_text(article_content)

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="Done")

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            brief = ArticleBrief(title="Test Ingest", content_type="Guide", slug="test-ingest")
            result = await pilot._run_pipeline(brief)

        assert result.success
        assert brief.status == ArticleStatus.completed
        pilot.smol_rag.ingest_text.assert_awaited_once_with(
            article_content, source_id="article-test-ingest"
        )

    @pytest.mark.asyncio
    async def test_pipeline_succeeds_when_ingestion_fails(self, setup):
        """RAG ingestion failure doesn't mark the article as failed."""
        pilot, posts_dir, queue_path = setup

        (posts_dir / "ingest-fail.md").write_text("Some content")
        pilot.smol_rag.ingest_text = AsyncMock(side_effect=Exception("RAG down"))

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(return_value="Done")

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            brief = ArticleBrief(title="Ingest Fail", content_type="Guide", slug="ingest-fail")
            result = await pilot._run_pipeline(brief)

        assert result.success
        assert brief.status == ArticleStatus.completed

    @pytest.mark.asyncio
    async def test_critic_failure_skips_revision(self, setup):
        """If the critic stage fails, pipeline stops before revision."""
        pilot, posts_dir, queue_path = setup

        call_count = 0

        async def mock_process(prompt):
            nonlocal call_count
            call_count += 1
            # Stages: 1=researcher, 2=planner, 3=writer, 4=critic (fail)
            if call_count == 4:
                raise Exception("Critic error")
            return "Done"

        mock_agent = MagicMock()
        mock_agent.process = AsyncMock(side_effect=mock_process)

        with patch("app.autopilot.build_agent_loop", return_value=mock_agent):
            brief = ArticleBrief(title="Critic Fail", content_type="Guide", slug="critic-fail")
            result = await pilot._run_pipeline(brief)

        assert not result.success
        assert brief.status == ArticleStatus.failed
        assert "critic" in brief.error
        assert call_count == 4  # Never reached revision


# ---------------------------------------------------------------------------
# ArticleStatus enum
# ---------------------------------------------------------------------------

class TestArticleStatus:
    def test_critiquing_exists(self):
        assert ArticleStatus.critiquing.value == "critiquing"

    def test_revising_exists(self):
        assert ArticleStatus.revising.value == "revising"

    def test_all_statuses(self):
        expected = {"pending", "researching", "planning", "writing", "critiquing", "revising", "completed", "failed", "skip"}
        actual = {s.value for s in ArticleStatus}
        assert actual == expected
