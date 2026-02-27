import re
from typing import List, Optional

from nltk.tokenize import sent_tokenize


def preserve_markdown_code_excerpts(
    content: str,
    n: int = 2000,
    overlap: Optional[int] = None,
) -> List[str]:
    """Split *content* into excerpts of at most *n* characters without breaking
    fenced code blocks (``` … ```).

    The algorithm keeps entire code blocks intact. If a code block plus its
    neighbouring paragraph both fit within *n*, they are merged so readers see
    the context together.

    Plain‑text paragraphs that still exceed *n* are further split into
    sentences using *nltk.sent_tokenize*.

    Parameters
    ----------
    content:
        The complete Markdown document.
    n:
        Maximum length of a single excerpt (characters). Default is ``2000``.
    overlap:
        If given (>0), the last *overlap* characters of each excerpt are
        prepended to the next excerpt. Use this to maintain context across
        boundaries. ``None`` → no overlap.

    Returns
    -------
    list[str]
        Ordered list of excerpts.
    """

    if n <= 0:
        return []

    def _flush(buf: list[str]) -> None:
        """Append the current buffer to *excerpts* if it contains anything."""
        if buf:
            txt = "\n\n".join(buf).strip()
            if txt:
                excerpts.append(txt)
            buf.clear()

    def _split_code_block(code_block: str) -> List[str]:
        code_block = code_block.strip()
        if len(code_block) <= n:
            return [code_block]

        lines = code_block.splitlines()
        if len(lines) < 2 or not lines[0].startswith("```") or not lines[-1].startswith("```"):
            return [code_block[i:i + n] for i in range(0, len(code_block), n)]

        opening = lines[0]
        closing = lines[-1]
        body = "\n".join(lines[1:-1])
        overhead = len(opening) + len(closing) + 2

        # Degenerate case: impossible to preserve fences within the requested limit.
        if overhead >= n:
            return [code_block[i:i + n] for i in range(0, len(code_block), n)]

        max_body_len = n - overhead
        return [
            f"{opening}\n{body[i:i + max_body_len]}\n{closing}"
            for i in range(0, len(body), max_body_len)
        ]

    def _append_text(chunk: str) -> None:
        """Append normal Markdown *chunk* into *buffer*, respecting *n*."""
        paragraphs = re.split(r"\n{2,}", chunk.strip())
        for para in paragraphs:
            if not para:
                continue

            # Paragraph boundaries are preserved as excerpt boundaries.
            if buffer:
                _flush(buffer)

            if len(para) <= n:
                buffer.append(para)
                continue

            # Paragraph still too big — split by sentences
            sentence_buffer = ""
            for sentence in sent_tokenize(para):
                sentence = sentence.strip()
                if not sentence:
                    continue

                # Extremely long sentences are hard‑split at *n*
                if len(sentence) > n:
                    if sentence_buffer:
                        excerpts.append(sentence_buffer)
                        sentence_buffer = ""
                    for i in range(0, len(sentence), n):
                        excerpts.append(sentence[i : i + n])
                    continue

                candidate = sentence if not sentence_buffer else f"{sentence_buffer} {sentence}"
                if len(candidate) > n:
                    excerpts.append(sentence_buffer)
                    sentence_buffer = sentence
                else:
                    sentence_buffer = candidate

            if sentence_buffer:
                excerpts.append(sentence_buffer)

    code_pattern = re.compile(r"(```.*?```)", re.DOTALL)
    parts = code_pattern.split(content)

    excerpts: list[str] = []
    buffer: list[str] = []

    for part in parts:
        if not part.strip():
            continue

        # --- Code block ---------------------------------------------------
        if part.startswith("```") and part.endswith("```"):
            code_block = part.strip()

            # Attempt to keep code with the current buffer
            if buffer and len("\n\n".join(buffer) + "\n\n" + code_block) <= n:
                buffer.append(code_block)
            else:
                _flush(buffer)

                excerpts.extend(_split_code_block(code_block))
            continue

        _append_text(part)

    _flush(buffer)
    if overlap and overlap > 0 and len(excerpts) > 1:
        overlapped: list[str] = []
        for i, ex in enumerate(excerpts):
            if i > 0:
                ex = excerpts[i - 1][-overlap:] + ex
            overlapped.append(ex)
        return overlapped

    return excerpts
