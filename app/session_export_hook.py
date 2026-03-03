import logging
from typing import Any, Dict

logger = logging.getLogger("smolclaw.session_export")


class SessionExportHook:
    """Hook that runs on session end to generate a journal and index the session.

    Configurable via flags: generate_journal, index_session.
    Errors in journal generation do not block session indexing.
    """

    def __init__(
        self,
        smol_rag,
        llm=None,
        memory_dir: str = "",
        enabled: bool = True,
        generate_journal: bool = True,
        index_session: bool = True,
    ):
        self.smol_rag = smol_rag
        self.llm = llm
        self.memory_dir = memory_dir
        self.enabled = enabled
        self.generate_journal = generate_journal
        self.index_session = index_session

    async def __call__(self, context: Dict[str, Any]):
        if not self.enabled:
            return

        session = context.get("session")
        if session is None:
            logger.warning("SessionExportHook: no session in context")
            return

        if self.generate_journal and self.llm:
            try:
                from app.journal import generate_journal
                await generate_journal(
                    session=session,
                    llm=self.llm,
                    smol_rag=self.smol_rag,
                    memory_dir=self.memory_dir,
                )
                logger.info(f"Journal generated for session {session.key}")
            except Exception as e:
                logger.warning(f"Journal generation failed for session {session.key}: {e}")

        if self.index_session:
            try:
                from app.session_indexer import index_session
                await index_session(
                    session=session,
                    smol_rag=self.smol_rag,
                    llm=self.llm,
                    memory_dir=self.memory_dir,
                )
                logger.info(f"Session indexed: {session.key}")
            except Exception as e:
                logger.warning(f"Session indexing failed for session {session.key}: {e}")
