import logging
import os
from typing import Optional

from app.session import Session, SessionManager
from app.storage_paths import contained_storage_path
from app.tools.memory_tools import format_memory_content

logger = logging.getLogger("smolclaw.session_indexer")


def parse_session_content(session: Session) -> str:
    """Concatenate user + assistant messages from a session, skipping tool calls."""
    parts = []
    for msg in session.messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


async def _extract_topics(content: str, llm) -> list[str]:
    """Use LLM to extract 3-5 topic tags from session content."""
    from app.utilities import extract_json_from_text
    prompt = (
        "Extract 3-5 short topic tags (single words or two-word phrases, lowercase, "
        "no hashtags) that summarise the main topics discussed in this conversation. "
        "Return as JSON: {\"topics\": [\"tag1\", \"tag2\", ...]}\n\n"
        f"Conversation:\n{content[:3000]}"
    )
    try:
        response = await llm.get_completion(prompt, use_cache=True)
        parsed = extract_json_from_text(response)
        if parsed and "topics" in parsed:
            return [str(t).lower().strip() for t in parsed["topics"][:5]]
    except Exception as e:
        logger.warning(f"Topic extraction failed: {e}")
    return []


async def index_session(
    session: Session,
    smol_rag,
    llm=None,
    memory_dir: Optional[str] = None,
) -> str:
    """Index a single session into SmolRAG as an episode memory type.

    Returns the source_id used for indexing.
    """
    content = parse_session_content(session)
    if not content.strip():
        return ""

    source_id = f"session-{session.key}"

    # Extract topics if LLM available
    tags = ["session", f"session_{session.key}"]
    if llm:
        topics = await _extract_topics(content, llm)
        tags.extend(topics)

    formatted = format_memory_content(
        content,
        memory_type="episode",
        tags=tags,
        source_id=source_id,
    )

    # Write to memory dir if provided
    if memory_dir:
        os.makedirs(memory_dir, exist_ok=True)
        file_path = contained_storage_path(memory_dir, source_id, ".md")
        with open(file_path, "w") as f:
            f.write(formatted)

    # Remove old version if exists, then ingest
    await smol_rag.remove_document_by_source(source_id)
    await smol_rag.ingest_text(formatted, source_id=source_id)

    logger.info(f"Indexed session {session.key} ({len(content)} chars)")
    return source_id


async def index_all_sessions(
    sessions_dir: str,
    smol_rag,
    llm=None,
    memory_dir: Optional[str] = None,
) -> dict[str, str]:
    """Index all .jsonl session files into SmolRAG.

    Returns a dict mapping session_key -> source_id.
    """
    session_manager = SessionManager(sessions_dir)
    results = {}

    for filename in os.listdir(sessions_dir):
        if not filename.endswith(".jsonl"):
            continue
        session = session_manager.load_file(os.path.join(sessions_dir, filename))
        if session is None:
            continue
        key = session.key

        content = parse_session_content(session)
        if not content.strip():
            logger.debug(f"Skipping empty session: {key}")
            continue

        source_id = await index_session(session, smol_rag, llm=llm, memory_dir=memory_dir)
        if source_id:
            results[key] = source_id

    logger.info(f"Indexed {len(results)} sessions from {sessions_dir}")
    return results
