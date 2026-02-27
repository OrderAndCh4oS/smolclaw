from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class MemoryType(str, Enum):
    FACT = "fact"
    DECISION = "decision"
    PREFERENCE = "preference"
    EPISODE = "episode"
    TASK = "task"
    JOURNAL = "journal"
    REFERENCE = "reference"


@dataclass
class MemoryMetadata:
    memory_type: MemoryType
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    source_file: Optional[str] = None
    confidence: float = 1.0
    tags: List[str] = field(default_factory=list)
    importance: float = 0.5

    def to_dict(self) -> dict:
        return {
            "memory_type": self.memory_type.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "source_file": self.source_file,
            "confidence": self.confidence,
            "tags": self.tags,
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryMetadata":
        return cls(
            memory_type=MemoryType(data["memory_type"]),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            source_file=data.get("source_file"),
            confidence=data.get("confidence", 1.0),
            tags=data.get("tags", []),
            importance=data.get("importance", 0.5),
        )


async def classify_chunk(content: str, llm) -> tuple[MemoryType, float]:
    """Use LLM to classify a chunk of content into a memory type with confidence."""
    from app.prompts import get_classify_memory_prompt
    from app.utilities import extract_json_from_text

    prompt = get_classify_memory_prompt(content)
    response = await llm.get_completion(prompt, use_cache=True)
    parsed = extract_json_from_text(response)

    if parsed and "memory_type" in parsed:
        try:
            memory_type = MemoryType(parsed["memory_type"])
            confidence = float(parsed.get("confidence", 0.7))
            return memory_type, min(max(confidence, 0.0), 1.0)
        except (ValueError, KeyError):
            pass

    return MemoryType.REFERENCE, 0.5
