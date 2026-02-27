FROM python:3.12-slim AS base

# Prevent Python from buffering stdout/stderr (important for Docker logs)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download NLTK punkt tokenizer (needed by chunking.py)
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# Copy application code
COPY app/ app/
COPY cli/ cli/
COPY agents/ agents/
COPY vault/docs/ vault/docs/
COPY vault/memory/ vault/memory/
COPY agents.yaml .
COPY AGENT.md .

# Create runtime directories (overridable via volume mounts)
RUN mkdir -p store cache logs sessions

# Non-root user
RUN useradd --create-home --shell /bin/bash smolclaw \
    && chown -R smolclaw:smolclaw /app
USER smolclaw

EXPOSE 18789

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import asyncio, websockets; asyncio.run(websockets.connect('ws://localhost:18789'))" || exit 1

ENTRYPOINT ["python", "-m", "cli.main", "serve"]
