# ==============================================================================
# Stage 1: Builder — Instalación rápida y reproducible con uv
# ==============================================================================
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.6.0 /uv /bin/uv

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN uv venv /.venv && \
    uv pip install --no-cache ".[gcp]"

# ==============================================================================
# Stage 2: Runtime — Contenedor liviano no-root (Local / Docker / Cloud Run)
# ==============================================================================
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -s /bin/bash -m appuser

WORKDIR /app

COPY --from=builder /.venv /.venv
ENV PATH="/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/.venv"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY src/ /app/src/
COPY sql/ /app/sql/
COPY web/ /app/web/
COPY data/demo/ /app/data/demo/
COPY pyproject.toml /app/

RUN mkdir -p /app/data/scraper-precios && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

CMD ["scraper-server"]
