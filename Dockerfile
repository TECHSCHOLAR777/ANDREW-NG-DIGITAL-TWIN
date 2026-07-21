# ============================================================
# Andrew Ng Digital Twin - backend API
#
# Two-stage build. The previous single-stage image kept the C
# toolchain in the final layer, ran as root, had no healthcheck, and
# downloaded the ~420MB embedding model at RUNTIME on first request,
# so a cold start blocked the first user for a minute or more and the
# container needed outbound Hugging Face access just to serve traffic.
# ============================================================

# ── Stage 1: build wheels ───────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

# CPU-only torch. The default wheel pulls CUDA libraries worth several
# gigabytes that are dead weight on a CPU inference host.
RUN pip install --upgrade pip \
 && pip wheel --wheel-dir /wheels \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt


# ── Stage 2: runtime ────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HF_HOME=/opt/models \
    SENTENCE_TRANSFORMERS_HOME=/opt/models \
    EMBED_MODEL=all-mpnet-base-v2

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

# Bake the embedding model into the image so the first request after a
# deploy does not pay for a 420MB download while the user waits.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-mpnet-base-v2'); print('embedding model baked into image')"

WORKDIR /code
COPY ./backend /code/backend

# Run unprivileged. /opt/models must stay readable by that user.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /opt/models /code
USER appuser

EXPOSE 8000

# Without a healthcheck a backend whose database pool has died keeps
# receiving traffic instead of being restarted.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}"]
