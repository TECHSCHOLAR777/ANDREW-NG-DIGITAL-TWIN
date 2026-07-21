"""
services/embeddings.py
─────────────────────────────────────────────────────────────────────────────
Pluggable embedding provider.

WHY THIS EXISTS
───────────────
The backend used to load all-mpnet-base-v2 into the API process. Measured, that
costs 852MB of peak RAM and a 1.4GB image, of which torch alone is 470MB. Every
free hosting tier is 512MB, so the embedding model was the single reason
deployment required a paid instance.

Gemini's embedding API returns 768-dimensional vectors when asked, which is
exactly what the schema already stores, so switching providers needs no
migration and no re-indexing of the column type. The runtime drops to roughly
200MB and fits a free tier.

    provider   RAM     image    cold start   cost
    local      852MB   1.4GB    30 to 60s    needs a paid instance
    gemini     ~200MB  ~200MB   ~3s          free tier, per-user keys

Local is kept, not deleted. It means development and tests work with no API key
and no network, which is worth more than the lines it costs.

ASYMMETRIC EMBEDDING
────────────────────
Gemini distinguishes RETRIEVAL_QUERY from RETRIEVAL_DOCUMENT. A question and
the passage answering it are not the same kind of text, and embedding them with
the same objective loses that. mpnet is symmetric and cannot express it, so
this is a genuine retrieval improvement that comes free with the switch.

Getting it backwards is worse than not using it at all, so the task type is
part of the function signature rather than a default anyone can forget.

RATE LIMITS
───────────
The free tier limit is REQUESTS PER DAY, not per minute:

    quota_id: EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier
    limit:    1000

The 429 body also carries a `retry in 8s` hint, which reads like a short
per-minute window and is not one. Waiting does not help; the counter resets at
midnight Pacific.

That makes REQUEST COUNT the only thing that matters, which makes batching the
whole game:

    SDK                          texts per request   1000 requests buys
    google.generativeai (old)    1                   1000 chunks
    google-genai (current)       up to 100           100,000 chunks

The deprecated SDK sends one HTTP request per text even when handed a list, so
a batch size set there changes nothing. If google-genai is missing, ingestion
silently costs 100x its quota, so _gemini_encode warns loudly on fallback
rather than degrading quietly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

# "gemini" keeps the API process small enough for a free tier.
# "local" runs sentence-transformers in-process; no API key, no network.
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "gemini").lower()

GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")
LOCAL_EMBED_MODEL = os.getenv("EMBED_MODEL", "all-mpnet-base-v2")

# The schema stores VECTOR(768). Changing this needs a migration and a full
# re-ingest, so it is deliberately not a casual knob.
EMBED_DIMS = int(os.getenv("EMBED_DIMS", "768"))

# 100 is the API's maximum texts per embed request. Since the free tier is
# capped on REQUESTS PER DAY, a smaller batch does not buy safety, it just
# spends the day's quota faster. This was 16, which cost 6x the requests for
# no benefit.
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "100"))

# Small gap between batches. Not a quota control (the quota is daily and
# nothing paced can help), just politeness so a burst of ~112 requests does not
# arrive as fast as the network allows.
EMBED_PACE_SECONDS = float(os.getenv("EMBED_PACE_SECONDS", "1.0"))

QUERY = "RETRIEVAL_QUERY"
DOCUMENT = "RETRIEVAL_DOCUMENT"


class EmbeddingError(RuntimeError):
    pass


class DailyQuotaExceeded(EmbeddingError):
    """
    The daily request cap is spent. Separate from EmbeddingError because the
    remedy is different: not "retry", but "come back after the reset". Callers
    that treat all embedding failures alike will retry this forever.
    """


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL PROVIDER
# ─────────────────────────────────────────────────────────────────────────────
_local_model = None
_local_pool = None


def _get_local_pool():
    global _local_pool
    if _local_pool is None:
        from concurrent.futures import ThreadPoolExecutor
        _local_pool = ThreadPoolExecutor(
            max_workers=int(os.getenv("EMBED_WORKERS", "2")),
            thread_name_prefix="embed",
        )
    return _local_pool


def _get_local_model():
    """Imported lazily so the gemini provider never pulls torch into memory."""
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading local embedding model %s ...", LOCAL_EMBED_MODEL)
        _local_model = SentenceTransformer(LOCAL_EMBED_MODEL)
        logger.info("Local embedding model ready.")
    return _local_model


def _local_encode(texts: list[str]) -> list[list[float]]:
    model = _get_local_model()
    return [v.tolist() for v in model.encode(texts, show_progress_bar=False)]


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI PROVIDER
# ─────────────────────────────────────────────────────────────────────────────
def _gemini_encode(texts: list[str], api_key: str, task_type: str) -> list[list[float]]:
    if not api_key:
        raise EmbeddingError(
            "EMBED_PROVIDER=gemini needs an API key. Queries use the caller's "
            "key; ingestion uses GEMINI_API_KEY."
        )

    try:
        from google import genai as genai_new
        from google.genai import types as genai_types
        client = genai_new.Client(api_key=api_key)
        resp = client.models.embed_content(
            model=GEMINI_EMBED_MODEL,
            contents=texts,
            config=genai_types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBED_DIMS,
            ),
        )
        return [list(e.values) for e in resp.embeddings]
    except ImportError:
        pass

    # Falling back is expensive, not merely deprecated: the old SDK sends one
    # request per text, and the free tier is capped on requests per day. A
    # missing package therefore cuts throughput 100x with no visible symptom
    # beyond an ingest that mysteriously stops. Say so.
    if not _warned_legacy_sdk:
        _warn_legacy_once()

    # configure() is process-global, which is a cross-request key leak in an
    # async server, so the call is serialised behind the same lock the
    # generation path uses.
    import google.generativeai as genai
    from . import gemini_client

    with gemini_client.legacy_lock():
        genai.configure(api_key=api_key)
        resp = genai.embed_content(
            model=GEMINI_EMBED_MODEL,
            content=texts,
            task_type=task_type,
            output_dimensionality=EMBED_DIMS,
        )
    emb = resp["embedding"]
    # Single input returns a flat vector; a list returns a list of vectors.
    return [emb] if emb and isinstance(emb[0], float) else emb


_warned_legacy_sdk = False


def _warn_legacy_once() -> None:
    global _warned_legacy_sdk
    _warned_legacy_sdk = True
    logger.warning(
        "google-genai is not installed, falling back to the deprecated "
        "google.generativeai SDK. That SDK sends ONE REQUEST PER TEXT, so "
        "batching is ineffective and bulk ingestion will exhaust the daily "
        "request quota after about %d chunks. Install it: pip install google-genai",
        1000,
    )


def _is_rate_limit(exc: BaseException) -> bool:
    m = str(exc).lower()
    return "429" in m or "quota" in m or "resource_exhausted" in m or "rate" in m


def _is_daily_quota(exc: BaseException) -> bool:
    """
    Distinguish the daily cap from a transient burst limit.

    They arrive as the same 429, but only one of them is worth waiting for.
    The daily one names itself in the violation:

        quota_id: EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier

    Retrying that burns eleven minutes to fail anyway, and worse, it buries the
    real answer ("come back tomorrow, or batch properly") under a generic
    rate-limit message.
    """
    m = str(exc).lower()
    return "perday" in m or "per day" in m or "requestsperday" in m


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────
def encode_sync(texts: list[str], api_key: str = "", task_type: str = DOCUMENT) -> list[list[float]]:
    if not texts:
        return []
    if EMBED_PROVIDER == "local":
        return _local_encode(texts)
    return _gemini_encode(texts, api_key, task_type)


async def embed_query(text: str, api_key: str = "") -> list[float]:
    """
    Embed one search query. Used on the request path, so it must be fast and
    must not raise for an ordinary hiccup.
    """
    loop = asyncio.get_running_loop()
    executor = _get_local_pool() if EMBED_PROVIDER == "local" else None
    vectors = await loop.run_in_executor(
        executor, lambda: encode_sync([text], api_key, QUERY)
    )
    return vectors[0]


async def embed_document(text: str, api_key: str = "") -> list[float]:
    """Embed one stored item, such as a knowledge graph entity name."""
    loop = asyncio.get_running_loop()
    executor = _get_local_pool() if EMBED_PROVIDER == "local" else None
    vectors = await loop.run_in_executor(
        executor, lambda: encode_sync([text], api_key, DOCUMENT)
    )
    return vectors[0]


def embed_documents(
    texts: list[str],
    api_key: str = "",
    batch_size: int = EMBED_BATCH_SIZE,
    on_progress=None,
) -> list[list[float]]:
    """
    Embed many documents, for ingestion.

    BATCHING, NOT PACING
    ────────────────────
    Two earlier versions of this function tried to solve the wrong problem. The
    first retried harder; the second paced slower. Both assumed a per-minute
    limit. The limit is per DAY, so neither could have worked: no arrangement
    of sleeps changes how many requests a day contains.

    What does change it is how many texts ride along in each request. At 100
    per request the same 1000-request quota covers 100,000 chunks instead of
    1000, which is the difference between an afternoon and eleven days.

    So the retry loop here is deliberately thin. It covers transient blips.
    A daily exhaustion is not retried at all, because waiting cannot fix it and
    pretending otherwise hides the real remedy.

    The caller's ingest is idempotent, so an interrupted run resumes safely.
    """
    if not texts:
        return []
    if EMBED_PROVIDER == "local":
        return _local_encode(texts)

    batch_size = max(1, min(batch_size, 100))   # 100 is the API maximum
    out: list[list[float]] = []

    i = 0
    while i < len(texts):
        batch = texts[i:i + batch_size]

        for attempt in range(5):
            try:
                out.extend(_gemini_encode(batch, api_key, DOCUMENT))
                break
            except Exception as exc:  # noqa: BLE001
                if _is_daily_quota(exc):
                    done = len(out)
                    raise DailyQuotaExceeded(
                        f"Daily embedding quota exhausted after {done} of "
                        f"{len(texts)} texts. This resets at midnight Pacific; "
                        f"waiting will not help. Re-run then, embedded files "
                        f"are skipped. If this happened early, check that "
                        f"google-genai is installed, since the fallback SDK "
                        f"spends 100x the quota."
                    ) from exc
                if not _is_rate_limit(exc):
                    raise EmbeddingError(f"Embedding failed at item {i}: {exc}") from exc
                if attempt == 4:
                    raise EmbeddingError(
                        f"Rate limited at item {i} after 5 attempts. Re-run to "
                        f"resume; already-embedded files are skipped."
                    ) from exc
                wait = min(5 * (attempt + 1), 30)
                logger.info("Rate limited at item %d, waiting %ds", i, wait)
                time.sleep(wait)

        i += batch_size
        if on_progress:
            on_progress(min(i, len(texts)), len(texts))
        if i < len(texts):
            time.sleep(EMBED_PACE_SECONDS)

    return out


def preload() -> None:
    """Warm the local model at startup. No-op for the API provider."""
    if EMBED_PROVIDER == "local":
        _get_local_model()


def describe() -> str:
    if EMBED_PROVIDER == "local":
        return f"local:{LOCAL_EMBED_MODEL} ({EMBED_DIMS}d)"
    return f"gemini:{GEMINI_EMBED_MODEL} ({EMBED_DIMS}d, asymmetric)"
