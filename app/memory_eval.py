"""Deterministic corpus-memory and knowledge-graph evaluation."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

import yaml

from app.ingestion import IngestionPipeline
from app.obsidian import parse_tags, parse_wiki_links
from app.storage_paths import atomic_write_json


REQUIRED_SUITE_FIELDS = {"id", "corpus", "questions"}
WORD_RE = re.compile(r"[A-Za-z0-9_/-]+")
MemoryEvalMode = Literal["deterministic", "rag", "answer"]


@dataclass(frozen=True)
class CorpusSource:
    source_id: str
    path: str
    title: str = ""
    kind: str = "external"
    metadata: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    body: str = ""


@dataclass(frozen=True)
class GraphRelationship:
    source: str
    relation: str
    target: str
    source_id: str

    def key(self) -> tuple[str, str, str]:
        return (
            self.source.strip().lower(),
            self.relation.strip().lower(),
            self.target.strip().lower(),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class CorpusClaim:
    source_id: str
    subject: str
    predicate: str
    object: str
    polarity: str = "positive"

    def key(self) -> tuple[str, str]:
        return (
            self.subject.strip().lower(),
            self.predicate.strip().lower(),
        )

    def value_key(self) -> tuple[str, str]:
        return (
            self.object.strip().lower(),
            self.polarity.strip().lower() or "positive",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "polarity": self.polarity,
        }


@dataclass(frozen=True)
class MemoryEvalQuestion:
    id: str
    query: str
    expected_sources: list[str] = field(default_factory=list)
    expected_entities: list[str] = field(default_factory=list)
    expected_relationships: list[GraphRelationship] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)
    min_source_hits: int = 1


@dataclass(frozen=True)
class MemoryEvalStalenessExpectation:
    id: str
    source_id: str
    expected: str = "fresh"
    max_age_days: int = 365
    as_of: str | None = None


@dataclass(frozen=True)
class MemoryEvalContradictionExpectation:
    id: str
    subject: str
    predicate: str
    sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryEvalSuite:
    id: str
    root_dir: str
    corpus: list[CorpusSource]
    questions: list[MemoryEvalQuestion]
    staleness: list[MemoryEvalStalenessExpectation] = field(default_factory=list)
    contradictions: list[MemoryEvalContradictionExpectation] = field(default_factory=list)


@dataclass
class MemoryEvalQuestionReport:
    question_id: str
    query: str
    score: float
    checks: dict[str, bool]
    retrieved_sources: list[str]
    matched_entities: list[str]
    matched_relationships: list[dict[str, str]]
    missing_sources: list[str] = field(default_factory=list)
    missing_entities: list[str] = field(default_factory=list)
    missing_relationships: list[dict[str, str]] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)
    retrieval_details: dict[str, Any] = field(default_factory=dict)
    answer: str = ""
    missing_citations: list[str] = field(default_factory=list)
    missing_source_kinds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "query": self.query,
            "score": self.score,
            "checks": self.checks,
            "retrieved_sources": self.retrieved_sources,
            "matched_entities": self.matched_entities,
            "matched_relationships": self.matched_relationships,
            "missing_sources": self.missing_sources,
            "missing_entities": self.missing_entities,
            "missing_relationships": self.missing_relationships,
            "missing_terms": self.missing_terms,
            "retrieval_details": self.retrieval_details,
            "answer": self.answer,
            "missing_citations": self.missing_citations,
            "missing_source_kinds": self.missing_source_kinds,
        }


@dataclass
class MemoryEvalHygieneReport:
    expectation_id: str
    check: str
    passed: bool
    score: float
    source_ids: list[str]
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectation_id": self.expectation_id,
            "check": self.check,
            "passed": self.passed,
            "score": self.score,
            "source_ids": self.source_ids,
            "details": self.details,
        }


@dataclass
class MemoryEvalReport:
    suite_id: str
    mode: MemoryEvalMode
    status: str
    score: float
    question_reports: list[MemoryEvalQuestionReport]
    corpus_size: int
    entity_count: int
    relationship_count: int
    hygiene_reports: list[MemoryEvalHygieneReport] = field(default_factory=list)
    output_path: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "mode": self.mode,
            "status": self.status,
            "score": self.score,
            "corpus_size": self.corpus_size,
            "entity_count": self.entity_count,
            "relationship_count": self.relationship_count,
            "hygiene": [report.to_dict() for report in self.hygiene_reports],
            "output_path": self.output_path,
            "created_at": self.created_at,
            "questions": [report.to_dict() for report in self.question_reports],
        }


def load_memory_eval_suite(path: str) -> MemoryEvalSuite:
    suite_path = os.path.abspath(path)
    with open(suite_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Memory eval YAML must contain an object.")
    missing = sorted(REQUIRED_SUITE_FIELDS - set(data))
    if missing:
        raise ValueError(f"Memory eval suite is missing required field(s): {', '.join(missing)}")

    root_dir = os.path.dirname(suite_path)
    corpus = [_load_corpus_source(root_dir, item) for item in _coerce_list(data["corpus"], "corpus")]
    questions = [
        _load_question(item)
        for item in _coerce_list(data["questions"], "questions")
    ]
    suite_id = str(data.get("id") or "").strip()
    if not suite_id:
        raise ValueError("Memory eval suite id cannot be empty.")
    if not corpus:
        raise ValueError("Memory eval suite corpus cannot be empty.")
    if not questions:
        raise ValueError("Memory eval suite questions cannot be empty.")
    return MemoryEvalSuite(
        id=suite_id,
        root_dir=root_dir,
        corpus=corpus,
        questions=questions,
        staleness=[
            _load_staleness_expectation(raw)
            for raw in _coerce_list(data.get("staleness", []), "staleness")
        ],
        contradictions=[
            _load_contradiction_expectation(raw)
            for raw in _coerce_list(data.get("contradictions", []), "contradictions")
        ],
    )


class CorpusMemoryIndex:
    """Small local index for testing corpus provenance and graph coverage."""

    def __init__(self, sources: list[CorpusSource]):
        self.sources = sources
        self.entities: dict[str, set[str]] = {}
        self.relationships: list[GraphRelationship] = []
        self.claims: list[CorpusClaim] = []
        self._build_graph()

    def search(self, query: str, *, top_k: int = 5) -> list[CorpusSource]:
        query_terms = _token_counts(query)
        if not query_terms:
            return self.sources[:top_k]
        scored = []
        for source in self.sources:
            body_terms = _token_counts(source.body)
            title_terms = _token_counts(source.title)
            score = 0.0
            for term, weight in query_terms.items():
                score += body_terms.get(term, 0) * weight
                score += title_terms.get(term, 0) * weight * 2
            if score > 0:
                scored.append((score, source))
        scored.sort(key=lambda item: (-item[0], item[1].source_id))
        return [source for _, source in scored[:top_k]]

    def relationships_for_sources(self, source_ids: set[str]) -> list[GraphRelationship]:
        return [rel for rel in self.relationships if rel.source_id in source_ids]

    def _build_graph(self):
        for source in self.sources:
            for entity in _coerce_string_list(source.metadata.get("entities"), "entities"):
                self._add_entity(entity, source.source_id)
            for tag in parse_tags(source.body):
                self._add_entity(f"#{tag}", source.source_id)
            for target, _alias in parse_wiki_links(source.body):
                self._add_entity(target, source.source_id)
                title = source.title or source.source_id
                self.relationships.append(GraphRelationship(
                    source=title,
                    relation="links_to",
                    target=target,
                    source_id=source.source_id,
                ))
            for raw in _coerce_list(source.metadata.get("relationships", []), "relationships"):
                if not isinstance(raw, dict):
                    raise ValueError("relationships entries must be objects.")
                rel = GraphRelationship(
                    source=str(raw.get("source") or "").strip(),
                    relation=str(raw.get("relation") or "related_to").strip(),
                    target=str(raw.get("target") or "").strip(),
                    source_id=source.source_id,
                )
                if not rel.source or not rel.target:
                    raise ValueError("relationships require source and target.")
                self._add_entity(rel.source, source.source_id)
                self._add_entity(rel.target, source.source_id)
                self.relationships.append(rel)
            for raw in _coerce_list(source.metadata.get("claims", []), "claims"):
                claim = _load_corpus_claim(raw, source.source_id)
                self._add_entity(claim.subject, source.source_id)
                self.claims.append(claim)

    def _add_entity(self, entity: str, source_id: str):
        normalized = entity.strip()
        if not normalized:
            return
        self.entities.setdefault(normalized.lower(), set()).add(source_id)


class MemoryEvalRunner:
    def __init__(
        self,
        *,
        mode: MemoryEvalMode = "deterministic",
        output_dir: str | None = None,
        top_k: int = 5,
        llm=None,
        answer_model: str | None = None,
        keep_rag_workspace: bool = False,
    ):
        if mode not in {"deterministic", "rag", "answer"}:
            raise ValueError(f"Unsupported memory eval mode: {mode}")
        self.mode = mode
        self.output_dir = output_dir
        self.top_k = max(1, top_k)
        self.llm = llm
        self.answer_model = answer_model
        self.keep_rag_workspace = keep_rag_workspace

    def run(self, suite_path: str) -> MemoryEvalReport:
        suite = load_memory_eval_suite(suite_path)
        if self.mode == "rag":
            return asyncio_run(self._run_rag(suite))
        if self.mode == "answer":
            return asyncio_run(self._run_answer(suite))
        return self._run_deterministic(suite)

    def _run_deterministic(self, suite: MemoryEvalSuite) -> MemoryEvalReport:
        index = CorpusMemoryIndex(suite.corpus)
        question_reports = [
            self._score_question(question, index)
            for question in suite.questions
        ]
        hygiene_reports = self._score_hygiene(suite, index)
        status, score = _report_status_and_score(question_reports, hygiene_reports)
        report = MemoryEvalReport(
            suite_id=suite.id,
            mode="deterministic",
            status=status,
            score=score,
            question_reports=question_reports,
            corpus_size=len(suite.corpus),
            entity_count=len(index.entities),
            relationship_count=len(index.relationships),
            hygiene_reports=hygiene_reports,
        )
        self._write_report(report)
        return report

    async def _run_rag(self, suite: MemoryEvalSuite) -> MemoryEvalReport:
        from app.smol_rag import create_smol_rag

        workspace = tempfile.mkdtemp(prefix=f"smolclaw-memory-eval-{suite.id}-")
        rag = create_smol_rag(
            llm=self.llm,
            db_path=os.path.join(workspace, "memory.db"),
            graph_path=os.path.join(workspace, "kg.graphml"),
            input_docs_dir=workspace,
        )
        try:
            for source in suite.corpus:
                await rag.ingest_text(source.content, source_id=source.source_id, source=source.kind)
            question_reports = [
                await self._score_question_with_rag(question, rag)
                for question in suite.questions
            ]
            index = CorpusMemoryIndex(suite.corpus)
            hygiene_reports = self._score_hygiene(suite, index)
            status, score = _report_status_and_score(question_reports, hygiene_reports)
            report = MemoryEvalReport(
                suite_id=suite.id,
                mode="rag",
                status=status,
                score=score,
                question_reports=question_reports,
                corpus_size=len(suite.corpus),
                entity_count=len(rag.graph.graph.nodes),
                relationship_count=len(rag.graph.graph.edges),
                hygiene_reports=hygiene_reports,
            )
            self._write_report(report)
            return report
        finally:
            await rag.close()
            if not self.keep_rag_workspace:
                shutil.rmtree(workspace, ignore_errors=True)

    async def _run_answer(self, suite: MemoryEvalSuite) -> MemoryEvalReport:
        llm, owns_llm = self._resolve_answer_llm()
        index = CorpusMemoryIndex(suite.corpus)
        source_by_id = {source.source_id: source for source in suite.corpus}
        try:
            question_reports = [
                await self._score_question_with_answer(question, index, source_by_id, llm)
                for question in suite.questions
            ]
            hygiene_reports = self._score_hygiene(suite, index)
            status, score = _report_status_and_score(question_reports, hygiene_reports)
            report = MemoryEvalReport(
                suite_id=suite.id,
                mode="answer",
                status=status,
                score=score,
                question_reports=question_reports,
                corpus_size=len(suite.corpus),
                entity_count=len(index.entities),
                relationship_count=len(index.relationships),
                hygiene_reports=hygiene_reports,
            )
            self._write_report(report)
            return report
        finally:
            if owns_llm:
                close_fn = getattr(llm, "close", None)
                if callable(close_fn):
                    result = close_fn()
                    if hasattr(result, "__await__"):
                        await result

    def _resolve_answer_llm(self):
        if self.llm is not None:
            return self.llm, False
        from app.llm import create_llm

        return create_llm(completion_model=self.answer_model), True

    def _score_question(
        self,
        question: MemoryEvalQuestion,
        index: CorpusMemoryIndex,
    ) -> MemoryEvalQuestionReport:
        retrieved = index.search(question.query, top_k=self.top_k)
        retrieved_ids = [source.source_id for source in retrieved]
        retrieved_id_set = set(retrieved_ids)
        source_hits = [source_id for source_id in question.expected_sources if source_id in retrieved_id_set]
        missing_sources = [
            source_id for source_id in question.expected_sources if source_id not in retrieved_id_set
        ]

        matched_entities = [
            entity for entity in question.expected_entities
            if entity.strip().lower() in index.entities
            and index.entities[entity.strip().lower()] & retrieved_id_set
        ]
        missing_entities = [
            entity for entity in question.expected_entities if entity not in matched_entities
        ]

        candidate_relationships = index.relationships_for_sources(retrieved_id_set)
        candidate_keys = {rel.key(): rel for rel in candidate_relationships}
        matched_relationships = []
        missing_relationships = []
        for expected in question.expected_relationships:
            match = candidate_keys.get(expected.key())
            if match:
                matched_relationships.append(match.to_dict())
            else:
                missing_relationships.append(expected.to_dict())

        retrieved_text = "\n\n".join(source.body for source in retrieved).lower()
        missing_terms = [
            term for term in question.required_terms
            if term.strip().lower() not in retrieved_text
        ]

        checks = {
            "source_retrieval": len(source_hits) >= question.min_source_hits,
            "entity_coverage": not missing_entities,
            "relationship_coverage": not missing_relationships,
            "term_coverage": not missing_terms,
        }
        score = sum(1 for ok in checks.values() if ok) / len(checks)
        return MemoryEvalQuestionReport(
            question_id=question.id,
            query=question.query,
            score=score,
            checks=checks,
            retrieved_sources=retrieved_ids,
            matched_entities=matched_entities,
            matched_relationships=matched_relationships,
            missing_sources=missing_sources,
            missing_entities=missing_entities,
            missing_relationships=missing_relationships,
            missing_terms=missing_terms,
            retrieval_details={"mode": "deterministic"},
        )

    async def _score_question_with_answer(
        self,
        question: MemoryEvalQuestion,
        index: CorpusMemoryIndex,
        source_by_id: dict[str, CorpusSource],
        llm,
    ) -> MemoryEvalQuestionReport:
        base = self._score_question(question, index)
        retrieved_sources = [
            source for source in index.search(question.query, top_k=self.top_k)
            if source.source_id in set(base.retrieved_sources)
        ]
        prompt = _answer_prompt(question, retrieved_sources)
        answer = await llm.get_completion(prompt)
        answer_text = str(answer or "")
        missing_citations = _missing_answer_citations(
            answer_text,
            question.expected_sources,
            source_by_id,
        )
        missing_source_kinds = _missing_source_kinds(
            answer_text,
            question.expected_sources,
            source_by_id,
        )
        checks = {
            **base.checks,
            "answer_citations": not missing_citations,
            "source_kind_distinction": not missing_source_kinds,
        }
        score = sum(1 for ok in checks.values() if ok) / len(checks)
        return MemoryEvalQuestionReport(
            question_id=base.question_id,
            query=base.query,
            score=score,
            checks=checks,
            retrieved_sources=base.retrieved_sources,
            matched_entities=base.matched_entities,
            matched_relationships=base.matched_relationships,
            missing_sources=base.missing_sources,
            missing_entities=base.missing_entities,
            missing_relationships=base.missing_relationships,
            missing_terms=base.missing_terms,
            retrieval_details={"mode": "answer", **base.retrieval_details},
            answer=answer_text,
            missing_citations=missing_citations,
            missing_source_kinds=missing_source_kinds,
        )

    def _score_hygiene(
        self,
        suite: MemoryEvalSuite,
        index: CorpusMemoryIndex,
    ) -> list[MemoryEvalHygieneReport]:
        source_by_id = {source.source_id: source for source in suite.corpus}
        reports = [
            _score_staleness_expectation(expectation, source_by_id)
            for expectation in suite.staleness
        ]
        reports.extend(
            _score_contradiction_expectation(expectation, index.claims)
            for expectation in suite.contradictions
        )
        return reports

    async def _score_question_with_rag(self, question: MemoryEvalQuestion, rag) -> MemoryEvalQuestionReport:
        vector_excerpt_ids: list[str] = []
        try:
            query_embedding = await rag.rate_limited_get_embedding(question.query)
            vector_results = await rag.vector_search(query_embedding, top_k=self.top_k)
            vector_excerpt_ids = [
                str(result["__id__"])
                for result in vector_results
                if result.get("__id__")
            ]
        except Exception:
            vector_excerpt_ids = []

        bm25_results = await rag.bm25_query(question.query, top_k=self.top_k)
        bm25_excerpt_ids = [
            str(result.get("excerpt_id") or result["doc_id"])
            for result in bm25_results
            if result.get("excerpt_id") or result.get("doc_id")
        ]
        vector_sources = await _source_ids_for_excerpts(rag, vector_excerpt_ids)
        bm25_sources = await _source_ids_for_excerpts(rag, bm25_excerpt_ids)
        retrieved_ids = _unique_strings([*vector_sources, *bm25_sources])
        retrieved_id_set = set(retrieved_ids)

        source_hits = [source_id for source_id in question.expected_sources if source_id in retrieved_id_set]
        missing_sources = [
            source_id for source_id in question.expected_sources if source_id not in retrieved_id_set
        ]

        matched_entities = [
            entity for entity in question.expected_entities
            if rag.get_graph_node(entity) is not None
        ]
        missing_entities = [
            entity for entity in question.expected_entities if entity not in matched_entities
        ]

        matched_relationships = []
        missing_relationships = []
        for expected in question.expected_relationships:
            edge = rag.get_graph_edge((expected.source, expected.target))
            if edge and _relationship_matches(edge, expected.relation):
                matched_relationships.append(expected.to_dict())
            else:
                missing_relationships.append(expected.to_dict())

        retrieved_excerpt_ids = _unique_strings([*vector_excerpt_ids, *bm25_excerpt_ids])
        retrieved_text_parts = []
        for excerpt_id in retrieved_excerpt_ids:
            data = await rag.get_excerpt(excerpt_id)
            if data and data.get("excerpt"):
                retrieved_text_parts.append(str(data["excerpt"]))
        retrieved_text = "\n\n".join(retrieved_text_parts).lower()
        missing_terms = [
            term for term in question.required_terms
            if term.strip().lower() not in retrieved_text
        ]

        checks = {
            "source_retrieval": len(source_hits) >= question.min_source_hits,
            "entity_coverage": not missing_entities,
            "relationship_coverage": not missing_relationships,
            "term_coverage": not missing_terms,
        }
        score = sum(1 for ok in checks.values() if ok) / len(checks)
        return MemoryEvalQuestionReport(
            question_id=question.id,
            query=question.query,
            score=score,
            checks=checks,
            retrieved_sources=retrieved_ids,
            matched_entities=matched_entities,
            matched_relationships=matched_relationships,
            missing_sources=missing_sources,
            missing_entities=missing_entities,
            missing_relationships=missing_relationships,
            missing_terms=missing_terms,
            retrieval_details={
                "mode": "rag",
                "vector_excerpt_ids": vector_excerpt_ids,
                "bm25_excerpt_ids": bm25_excerpt_ids,
                "vector_sources": vector_sources,
                "bm25_sources": bm25_sources,
            },
        )

    def _write_report(self, report: MemoryEvalReport):
        if not self.output_dir:
            return
        os.makedirs(self.output_dir, exist_ok=True)
        suffix_by_mode = {
            "deterministic": "memory-eval",
            "rag": "rag-memory-eval",
            "answer": "answer-memory-eval",
        }
        suffix = suffix_by_mode[report.mode]
        report.output_path = os.path.join(self.output_dir, f"{report.suite_id}.{suffix}.json")
        atomic_write_json(report.output_path, report.to_dict())


def memory_eval_report_to_json(report: MemoryEvalReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def memory_eval_suite_report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)


def build_memory_eval_suite_report(
    reports: list[MemoryEvalReport],
    *,
    baseline: dict[str, float] | None = None,
) -> dict[str, Any]:
    baseline = baseline or {}
    passed = sum(1 for report in reports if report.status == "passed")
    failed = len(reports) - passed
    raw_check_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    score_deltas: dict[str, dict[str, float | None]] = {}
    for report in reports:
        for question_report in report.question_reports:
            for check, ok in question_report.checks.items():
                raw_check_counts[check][1] += 1
                if ok:
                    raw_check_counts[check][0] += 1
        for hygiene_report in report.hygiene_reports:
            raw_check_counts[hygiene_report.check][1] += 1
            if hygiene_report.passed:
                raw_check_counts[hygiene_report.check][0] += 1
        baseline_score = baseline.get(report.suite_id)
        score_deltas[report.suite_id] = {
            "current": report.score,
            "baseline": baseline_score,
            "delta": None if baseline_score is None else report.score - baseline_score,
        }
    check_counts = {
        check: {
            "passed": passed_count,
            "total": total,
            "rate": passed_count / total if total else 0.0,
        }
        for check, (passed_count, total) in sorted(raw_check_counts.items())
    }
    average_score = (
        sum(report.score for report in reports) / len(reports)
        if reports
        else 0.0
    )
    return {
        "status": "passed" if failed == 0 else "failed",
        "mode": reports[0].mode if reports else None,
        "suite_count": len(reports),
        "passed": passed,
        "failed": failed,
        "average_score": average_score,
        "checks": check_counts,
        "score_deltas": score_deltas,
        "reports": [report.to_dict() for report in reports],
        "created_at": time.time(),
    }


def memory_eval_regressions(
    suite_report: dict[str, Any],
    *,
    max_score_drop: float = 0.0,
) -> list[dict[str, Any]]:
    """Return score deltas that exceed the allowed drop from baseline."""
    regressions = []
    score_deltas = suite_report.get("score_deltas")
    if not isinstance(score_deltas, dict):
        return regressions
    for suite_id, payload in score_deltas.items():
        if not isinstance(payload, dict):
            continue
        delta = payload.get("delta")
        if not isinstance(delta, (int, float)):
            continue
        if delta < -abs(max_score_drop):
            regressions.append({
                "suite_id": str(suite_id),
                "current": payload.get("current"),
                "baseline": payload.get("baseline"),
                "delta": float(delta),
                "max_score_drop": abs(max_score_drop),
            })
    return regressions


def load_memory_eval_baseline_scores(path: str) -> dict[str, float]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    scores: dict[str, float] = {}
    if isinstance(payload, dict) and isinstance(payload.get("reports"), list):
        for report in payload["reports"]:
            if isinstance(report, dict) and "suite_id" in report and "score" in report:
                scores[str(report["suite_id"])] = float(report["score"])
        return scores
    if isinstance(payload, dict) and "suite_id" in payload and "score" in payload:
        return {str(payload["suite_id"]): float(payload["score"])}
    if isinstance(payload, dict):
        for suite_id, value in payload.items():
            if isinstance(value, dict) and "score" in value:
                scores[str(suite_id)] = float(value["score"])
            elif isinstance(value, (int, float)):
                scores[str(suite_id)] = float(value)
    return scores


def load_latest_memory_eval_summary(evals_dir: str | None) -> str | None:
    """Return a compact agent-facing summary of the newest memory eval report."""
    if not evals_dir or not os.path.isdir(evals_dir):
        return None
    candidates: list[str] = []
    for root, _dirs, files in os.walk(evals_dir):
        for filename in files:
            if filename.endswith((
                ".memory-eval.json",
                ".rag-memory-eval.json",
                ".answer-memory-eval.json",
            )):
                candidates.append(os.path.join(root, filename))
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: os.path.getmtime(path))
    try:
        with open(latest, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _memory_eval_summary_from_report(payload, latest)


def asyncio_run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("MemoryEvalRunner(mode='rag') cannot run inside an active event loop.")


def _load_corpus_source(root_dir: str, item: Any) -> CorpusSource:
    if not isinstance(item, dict):
        raise ValueError("corpus entries must be objects.")
    rel_path = str(item.get("path") or "").strip()
    if not rel_path:
        raise ValueError("corpus entries require path.")
    source_path = os.path.realpath(os.path.join(root_dir, rel_path))
    if os.path.commonpath([os.path.realpath(root_dir), source_path]) != os.path.realpath(root_dir):
        raise ValueError(f"Corpus path escapes suite directory: {rel_path}")
    if not os.path.exists(source_path):
        raise ValueError(f"Corpus source is missing: {rel_path}")
    with open(source_path, encoding="utf-8") as handle:
        content = handle.read()
    metadata = IngestionPipeline._extract_frontmatter(content)
    body = IngestionPipeline._strip_frontmatter(content)
    source_id = str(item.get("source_id") or metadata.get("source_id") or rel_path).strip()
    title = str(item.get("title") or metadata.get("title") or os.path.splitext(os.path.basename(rel_path))[0])
    kind = str(item.get("kind") or metadata.get("kind") or metadata.get("memory_type") or "external")
    merged_metadata = {**metadata, **{k: v for k, v in item.items() if k not in {"path", "source_id", "title", "kind"}}}
    return CorpusSource(
        source_id=source_id,
        path=source_path,
        title=title,
        kind=kind,
        metadata=merged_metadata,
        content=content,
        body=body,
    )


def _memory_eval_summary_from_report(payload: dict[str, Any], path: str) -> str | None:
    suite_id = str(payload.get("suite_id") or "").strip()
    mode = str(payload.get("mode") or "").strip()
    status = str(payload.get("status") or "").strip()
    score = payload.get("score")
    if not suite_id or not status:
        return None

    failed_checks: list[str] = []
    for question in payload.get("questions", []):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("question_id") or "unknown")
        checks = question.get("checks") or {}
        if not isinstance(checks, dict):
            continue
        for check, ok in checks.items():
            if ok is False:
                failed_checks.append(f"{question_id}:{check}")
    for hygiene in payload.get("hygiene", []):
        if not isinstance(hygiene, dict):
            continue
        if hygiene.get("passed") is False:
            check = str(hygiene.get("check") or "hygiene")
            expectation_id = str(hygiene.get("expectation_id") or "unknown")
            failed_checks.append(f"{expectation_id}:{check}")

    score_text = f"{float(score):.3f}" if isinstance(score, (int, float)) else str(score or "unknown")
    lines = [
        f"Latest memory eval: {suite_id} ({mode or 'unknown mode'}) status={status}, score={score_text}.",
    ]
    if failed_checks:
        lines.append("Failed checks: " + ", ".join(failed_checks[:8]) + (" ..." if len(failed_checks) > 8 else ""))
        lines.append(
            "Treat affected memory as unverified until refreshed; cite source IDs/URLs and distinguish produced project writing from sourced external evidence."
        )
    else:
        lines.append(
            "Memory corpus checks passed; still cite source IDs/URLs for factual claims and call memory tools when prior project context may matter."
        )
    lines.append(f"Report: {path}")
    return "\n".join(lines)


def _load_question(item: Any) -> MemoryEvalQuestion:
    if not isinstance(item, dict):
        raise ValueError("questions entries must be objects.")
    question_id = str(item.get("id") or "").strip()
    query = str(item.get("query") or "").strip()
    if not question_id:
        raise ValueError("questions require id.")
    if not query:
        raise ValueError("questions require query.")
    return MemoryEvalQuestion(
        id=question_id,
        query=query,
        expected_sources=_coerce_string_list(item.get("expected_sources"), "expected_sources"),
        expected_entities=_coerce_string_list(item.get("expected_entities"), "expected_entities"),
        expected_relationships=[
            _load_expected_relationship(raw)
            for raw in _coerce_list(item.get("expected_relationships", []), "expected_relationships")
        ],
        required_terms=_coerce_string_list(item.get("required_terms"), "required_terms"),
        min_source_hits=int(item.get("min_source_hits", 1)),
    )


def _load_staleness_expectation(raw: Any) -> MemoryEvalStalenessExpectation:
    if not isinstance(raw, dict):
        raise ValueError("staleness entries must be objects.")
    source_id = str(raw.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("staleness entries require source_id.")
    expectation_id = str(raw.get("id") or source_id).strip()
    expected = str(raw.get("expected") or "fresh").strip().lower()
    if expected not in {"fresh", "stale"}:
        raise ValueError("staleness expected must be 'fresh' or 'stale'.")
    return MemoryEvalStalenessExpectation(
        id=expectation_id,
        source_id=source_id,
        expected=expected,
        max_age_days=int(raw.get("max_age_days", 365)),
        as_of=str(raw["as_of"]).strip() if raw.get("as_of") is not None else None,
    )


def _load_contradiction_expectation(raw: Any) -> MemoryEvalContradictionExpectation:
    if not isinstance(raw, dict):
        raise ValueError("contradictions entries must be objects.")
    subject = str(raw.get("subject") or "").strip()
    predicate = str(raw.get("predicate") or "").strip()
    if not subject or not predicate:
        raise ValueError("contradictions entries require subject and predicate.")
    expectation_id = str(raw.get("id") or f"{subject}:{predicate}").strip()
    return MemoryEvalContradictionExpectation(
        id=expectation_id,
        subject=subject,
        predicate=predicate,
        sources=_coerce_string_list(raw.get("sources"), "sources"),
    )


def _load_expected_relationship(raw: Any) -> GraphRelationship:
    if not isinstance(raw, dict):
        raise ValueError("expected_relationships entries must be objects.")
    return GraphRelationship(
        source=str(raw.get("source") or "").strip(),
        relation=str(raw.get("relation") or "related_to").strip(),
        target=str(raw.get("target") or "").strip(),
        source_id=str(raw.get("source_id") or "").strip(),
    )


def _load_corpus_claim(raw: Any, source_id: str) -> CorpusClaim:
    if not isinstance(raw, dict):
        raise ValueError("claims entries must be objects.")
    subject = str(raw.get("subject") or "").strip()
    predicate = str(raw.get("predicate") or "").strip()
    obj = str(raw.get("object") or raw.get("value") or "").strip()
    if not subject or not predicate or not obj:
        raise ValueError("claims require subject, predicate, and object.")
    return CorpusClaim(
        source_id=source_id,
        subject=subject,
        predicate=predicate,
        object=obj,
        polarity=str(raw.get("polarity") or "positive").strip() or "positive",
    )


def _report_status_and_score(
    question_reports: list[MemoryEvalQuestionReport],
    hygiene_reports: list[MemoryEvalHygieneReport],
) -> tuple[str, float]:
    scores = [report.score for report in question_reports]
    scores.extend(report.score for report in hygiene_reports)
    score = sum(scores) / len(scores) if scores else 0.0
    question_passed = all(report.score == 1.0 for report in question_reports)
    hygiene_passed = all(report.passed for report in hygiene_reports)
    return ("passed" if question_passed and hygiene_passed else "failed", score)


def _score_staleness_expectation(
    expectation: MemoryEvalStalenessExpectation,
    source_by_id: dict[str, CorpusSource],
) -> MemoryEvalHygieneReport:
    source = source_by_id.get(expectation.source_id)
    details: dict[str, Any] = {
        "expected": expectation.expected,
        "max_age_days": expectation.max_age_days,
        "as_of": expectation.as_of,
    }
    if not source:
        details["missing_source"] = True
        return MemoryEvalHygieneReport(
            expectation_id=expectation.id,
            check="staleness",
            passed=False,
            score=0.0,
            source_ids=[expectation.source_id],
            details=details,
        )

    captured_at = source.metadata.get("captured_at")
    details["captured_at"] = str(captured_at or "")
    captured_date = _parse_date(captured_at)
    as_of = _parse_date(expectation.as_of) or datetime.now(timezone.utc).date()
    if captured_date is None:
        details["missing_captured_at"] = True
        passed = False
    else:
        age_days = (as_of - captured_date).days
        is_stale = age_days > expectation.max_age_days
        details["age_days"] = age_days
        details["actual"] = "stale" if is_stale else "fresh"
        passed = details["actual"] == expectation.expected
    return MemoryEvalHygieneReport(
        expectation_id=expectation.id,
        check="staleness",
        passed=passed,
        score=1.0 if passed else 0.0,
        source_ids=[expectation.source_id],
        details=details,
    )


def _score_contradiction_expectation(
    expectation: MemoryEvalContradictionExpectation,
    claims: list[CorpusClaim],
) -> MemoryEvalHygieneReport:
    key = (expectation.subject.strip().lower(), expectation.predicate.strip().lower())
    matching = [claim for claim in claims if claim.key() == key]
    source_filter = set(expectation.sources)
    if source_filter:
        matching = [claim for claim in matching if claim.source_id in source_filter]
    values: dict[tuple[str, str], list[CorpusClaim]] = defaultdict(list)
    for claim in matching:
        values[claim.value_key()].append(claim)
    conflicting_values = [
        claim.to_dict()
        for value_claims in values.values()
        for claim in value_claims
    ] if len(values) > 1 else []
    matched_sources = _unique_strings([claim["source_id"] for claim in conflicting_values])
    passed = len(values) > 1 and (
        not source_filter or source_filter.issubset(set(matched_sources))
    )
    return MemoryEvalHygieneReport(
        expectation_id=expectation.id,
        check="contradiction",
        passed=passed,
        score=1.0 if passed else 0.0,
        source_ids=expectation.sources or matched_sources,
        details={
            "subject": expectation.subject,
            "predicate": expectation.predicate,
            "matched_claims": conflicting_values,
            "missing_sources": sorted(source_filter - set(matched_sources)),
        },
    )


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _token_counts(text: str) -> Counter:
    return Counter(token.lower() for token in WORD_RE.findall(text or ""))


async def _source_ids_for_excerpts(rag, excerpt_ids: list[str]) -> list[str]:
    source_ids = []
    for excerpt_id in excerpt_ids:
        doc_ids = await rag.doc_excerpt_map.get_by_right(excerpt_id)
        for doc_id in doc_ids:
            source_ids.extend(await rag.source_doc_map.get_by_right(doc_id))
    return _unique_strings(source_ids)


def _relationship_matches(edge: dict, relation: str) -> bool:
    needle = relation.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        str(edge.get(key) or "")
        for key in ("description", "keywords", "relation")
    ).lower()
    return needle in haystack


def _answer_prompt(question: MemoryEvalQuestion, sources: list[CorpusSource]) -> str:
    source_blocks = []
    for source in sources:
        source_blocks.append(
            "\n".join([
                f"Source ID: {source.source_id}",
                f"Title: {source.title}",
                f"Kind: {source.kind}",
                f"URL: {source.metadata.get('source_url') or ''}",
                "Excerpt:",
                source.body.strip(),
            ])
        )
    context = "\n\n---\n\n".join(source_blocks)
    return (
        "Answer the question using only the provided sources.\n"
        "Cite every supporting source by Source ID. When a source has a URL, include it. "
        "Distinguish produced/project writing from sourced/external evidence by naming each cited source's Kind.\n\n"
        f"Question: {question.query}\n\n"
        f"Sources:\n{context}\n\n"
        "Return a concise answer with citations."
    )


def _missing_answer_citations(
    answer: str,
    expected_sources: list[str],
    source_by_id: dict[str, CorpusSource],
) -> list[str]:
    answer_lower = answer.lower()
    missing = []
    for source_id in expected_sources:
        source = source_by_id.get(source_id)
        url = str(source.metadata.get("source_url") or "").lower() if source else ""
        cited_by_id = source_id.lower() in answer_lower
        cited_by_url = bool(url and url in answer_lower)
        if not cited_by_id and not cited_by_url:
            missing.append(source_id)
    return missing


def _missing_source_kinds(
    answer: str,
    expected_sources: list[str],
    source_by_id: dict[str, CorpusSource],
) -> list[str]:
    answer_lower = answer.lower()
    missing = []
    for source_id in expected_sources:
        source = source_by_id.get(source_id)
        if not source:
            continue
        kind = source.kind.strip().lower()
        if kind and kind not in answer_lower:
            missing.append(source_id)
    return missing


def _unique_strings(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _coerce_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_list(value: Any, field_name: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return value
