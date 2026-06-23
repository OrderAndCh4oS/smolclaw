import logging
import os
from datetime import datetime, timezone

from app.session import Session
from app.storage_paths import atomic_write_text, contained_storage_path
from app.tools.memory_tools import format_memory_content

logger = logging.getLogger("smolclaw.journal")


async def generate_journal(
    session: Session,
    llm,
    smol_rag,
    memory_dir: str,
) -> str:
    """Generate a first-person session reflection journal entry.

    The journal is auto-classified as memory_type: journal, written to
    the memory directory as markdown with frontmatter, and ingested into SmolRAG.
    """
    from app.prompts import get_journal_prompt

    # Build conversation text from session
    conversation_parts = []
    for msg in session.messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content and role in ("user", "assistant"):
            conversation_parts.append(f"{role}: {content}")

    if not conversation_parts:
        return ""

    conversation_text = "\n".join(conversation_parts)
    prompt = get_journal_prompt(conversation_text)

    journal_content = await llm.get_completion(prompt, use_cache=False)
    journal_content = journal_content.strip()

    if not journal_content:
        return ""

    source_id = f"journal-{session.key}"

    # Format with taxonomy
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    formatted = format_memory_content(
        journal_content,
        memory_type="journal",
        tags=["session_reflection", f"date_{timestamp}"],
        source_id=source_id,
    )

    # Write to memory directory
    os.makedirs(memory_dir, exist_ok=True)
    file_path = contained_storage_path(memory_dir, source_id, ".md")
    atomic_write_text(file_path, formatted)

    # Re-exporting the same session should overwrite the prior journal.
    await smol_rag.remove_document_by_source(source_id)
    await smol_rag.ingest_text(formatted, source_id=source_id)

    logger.info(f"Journal generated: {source_id} ({len(journal_content)} chars)")
    return journal_content
