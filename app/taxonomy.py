from enum import Enum


class MemoryType(str, Enum):
    FACT = "fact"
    DECISION = "decision"
    PREFERENCE = "preference"
    EPISODE = "episode"
    TASK = "task"
    JOURNAL = "journal"
    REFERENCE = "reference"


async def classify_chunk(content: str, llm) -> tuple[MemoryType, float]:
    """Use LLM to classify a chunk of content into a memory type with confidence."""
    from app.prompts import get_classify_memory_prompt

    prompt = get_classify_memory_prompt(content)

    # Try structured output first
    if hasattr(llm, "get_structured_completion"):
        try:
            from app.schemas import MemoryClassification
            result = await llm.get_structured_completion(prompt, MemoryClassification, use_cache=True)
            memory_type = MemoryType(result.memory_type)
            return memory_type, result.confidence
        except Exception:
            pass  # Fall through to text-based parsing

    # Fallback: text-based parsing
    from app.utilities import extract_json_from_text
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
