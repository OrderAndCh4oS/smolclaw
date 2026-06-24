FROM python:3.12-slim AS base

# Prevent Python from buffering stdout/stderr (important for Docker logs)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NLTK_DATA=/usr/local/share/nltk_data

WORKDIR /app

# Copy application code and package metadata
COPY pyproject.toml README.md ./
COPY app/ app/
COPY cli/ cli/
COPY agents/ agents/
COPY agents.yaml .
COPY AGENT.md .

# Install from pyproject.toml, the dependency source of truth.
RUN pip install --no-cache-dir .

# Download NLTK corpora used by chunking and BM25.
RUN python -c "import nltk; d='/usr/local/share/nltk_data'; nltk.download('punkt', download_dir=d, quiet=True); nltk.download('punkt_tab', download_dir=d, quiet=True); nltk.download('stopwords', download_dir=d, quiet=True)"

# Pre-download tiktoken encodings (needed at runtime, no network in container)
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')"

# Create runtime directories (overridable via volume mounts)
RUN mkdir -p store cache logs sessions memory

# Non-root user
RUN useradd --create-home --shell /bin/bash smolclaw \
    && chown -R smolclaw:smolclaw /app
USER smolclaw

EXPOSE 18789

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import asyncio, websockets; asyncio.run(websockets.connect('ws://localhost:18789').__aenter__())" || exit 1

ENTRYPOINT ["python", "-m", "cli.main", "serve"]
