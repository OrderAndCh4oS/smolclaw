"""Pydantic models for structured LLM responses."""

from typing import Literal

from pydantic import BaseModel, Field


class MemoryClassification(BaseModel):
    memory_type: Literal["fact", "decision", "preference", "episode", "task", "journal", "reference"]
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedEntity(BaseModel):
    entity_name: str
    entity_type: str
    entity_description: str


class ExtractedRelationship(BaseModel):
    source_entity: str
    target_entity: str
    relationship_description: str
    relationship_keywords: str
    relationship_strength: float = Field(ge=0.0, le=1.0)


class EntityExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    content_keywords: list[str] = Field(default_factory=list)


class ContradictionVerdict(BaseModel):
    verdict: Literal["agree", "contradict", "ambiguous"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class HighLowKeywords(BaseModel):
    high_level_keywords: list[str] = Field(default_factory=list)
    low_level_keywords: list[str] = Field(default_factory=list)


class RouteDecision(BaseModel):
    selected_route: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
