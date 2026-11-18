# ─────────────────────────────────────────────────────────────────────────────
# Zumra MCP — Dockerfile
# Multi-stage, minimal Python 3.12-slim image.
# Compatible with Koyeb, Render, and Hugging Face Spaces.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools only in the builder stage
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user for security
RUN useradd --create-home --shell /bin/bash zumra
WORKDIR /app

# Copy pre-built packages from the builder
COPY --from=builder /install /usr/local

# Copy application source & assets
COPY main.py .
COPY firebase_service.py .
COPY icon.png .
COPY logo.svg .
COPY favicon.ico .
COPY public ./public
# .env is NOT copied — secrets are injected via environment variables at runtime

# Drop to non-root
USER zumra

# Cloud platforms inject PORT; 8000 is the local default
ENV PORT=8000
EXPOSE 8000

# Health check for orchestrators
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')"

# Start the server
CMD ["sh", "-c", "python main.py"]
