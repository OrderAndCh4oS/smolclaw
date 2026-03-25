"""Tests for Pydantic schemas."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    ContradictionVerdict,
    EntityExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    HighLowKeywords,
    MemoryClassification,
    RouteDecision,
)


class TestMemoryClassification:
    def test_valid(self):
        m = MemoryClassification(memory_type="fact", confidence=0.9)
        assert m.memory_type == "fact"
        assert m.confidence == 0.9

    def test_all_types(self):
        for t in ("fact", "decision", "preference", "episode", "task", "journal", "reference"):
            m = MemoryClassification(memory_type=t, confidence=0.5)
            assert m.memory_type == t

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            MemoryClassification(memory_type="unknown", confidence=0.5)

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            MemoryClassification(memory_type="fact", confidence=1.5)
        with pytest.raises(ValidationError):
            MemoryClassification(memory_type="fact", confidence=-0.1)

    def test_confidence_boundaries(self):
        MemoryClassification(memory_type="fact", confidence=0.0)
        MemoryClassification(memory_type="fact", confidence=1.0)


class TestContradictionVerdict:
    def test_valid(self):
        v = ContradictionVerdict(verdict="agree", confidence=0.8, reasoning="Same info")
        assert v.verdict == "agree"

    def test_all_verdicts(self):
        for vtype in ("agree", "contradict", "ambiguous"):
            ContradictionVerdict(verdict=vtype, confidence=0.5, reasoning="test")

    def test_invalid_verdict(self):
        with pytest.raises(ValidationError):
            ContradictionVerdict(verdict="maybe", confidence=0.5, reasoning="test")


class TestEntityExtractionResult:
    def test_empty(self):
        r = EntityExtractionResult()
        assert r.entities == []
        assert r.relationships == []
        assert r.content_keywords == []

    def test_with_data(self):
        r = EntityExtractionResult(
            entities=[ExtractedEntity(
                entity_name="Python", entity_type="language", entity_description="A programming language",
            )],
            relationships=[ExtractedRelationship(
                source_entity="FastAPI", target_entity="Python",
                relationship_description="Built with",
                relationship_keywords="framework",
                relationship_strength=0.9,
            )],
            content_keywords=["python", "fastapi"],
        )
        assert len(r.entities) == 1
        assert r.entities[0].entity_name == "Python"
        assert len(r.relationships) == 1
        assert r.relationships[0].relationship_strength == 0.9


class TestHighLowKeywords:
    def test_empty(self):
        h = HighLowKeywords()
        assert h.high_level_keywords == []
        assert h.low_level_keywords == []

    def test_with_data(self):
        h = HighLowKeywords(
            high_level_keywords=["AI", "Machine Learning"],
            low_level_keywords=["neural networks", "backpropagation"],
        )
        assert len(h.high_level_keywords) == 2


class TestRouteDecision:
    def test_valid(self):
        r = RouteDecision(selected_route="researcher", confidence=0.85, reasoning="Research query")
        assert r.selected_route == "researcher"

    def test_roundtrip(self):
        r = RouteDecision(selected_route="coder", confidence=0.9, reasoning="Code task")
        d = r.model_dump()
        r2 = RouteDecision.model_validate(d)
        assert r == r2
