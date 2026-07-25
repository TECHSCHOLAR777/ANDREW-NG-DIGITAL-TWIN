# ============================================================
# Andrew Ng Digital Twin - backend API
#
# Embeddings come from an external API (EMBED_PROVIDER=jina by default), so
# this image carries no torch and no model weights.
#
# Keeping embeddings outside the API image substantially reduces image size,
# memory pressure, and cold-start time.
#
# To run embeddings in-process instead, install the local extras and set
# EMBED_PROVIDER=local. That is a development convenience, not a deployment
# target: it puts torch back and the memory with it.
# ============================================================

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential is needed only to compile wheels, and is left behind in this
# stage rather than shipped.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip && pip wheel --wheel-dir /wheels -r requirements.txt


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    EMBED_PROVIDER=jina

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

WORKDIR /code
COPY ./backend /code/backend

# Unprivileged.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /code
USER appuser

EXPOSE 8000

# Without this, a backend whose database pool has died keeps taking traffic
# instead of being restarted. start-period is short now that there is no model
# to load at boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}"]
