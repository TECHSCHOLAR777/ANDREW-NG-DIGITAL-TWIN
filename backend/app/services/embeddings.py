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
import re
import time

logger = logging.getLogger(__name__)

# Provider selection.
#   "jina"   — Jina AI API. The default. 10M free tokens (no card), jina-embeddings-v3,
#              1024-dim, asymmetric retrieval.query/retrieval.passage, 100 RPM /
#              100K TPM on the free tier. No batch size limit.
#   "voyage" — Voyage AI API. 200M free tokens but requires adding a payment
#              method to unlock standard rate limits (3 RPM without card).
#   "gemini" — Gemini embedding API. Free but ~1000 texts/day per-minute cap
#              makes bulk ingest very slow.
#   "local"  — sentence-transformers in-process; no key, no network, but puts
#              torch back in the image. Development and tests only.
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "jina").lower()

JINA_EMBED_MODEL = os.getenv("JINA_EMBED_MODEL", "jina-embeddings-v3")
VOYAGE_EMBED_MODEL = os.getenv("VOYAGE_EMBED_MODEL", "voyage-4-lite")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")
LOCAL_EMBED_MODEL = os.getenv("EMBED_MODEL", "all-mpnet-base-v2")

# The schema stores VECTOR(<EMBED_DIMS>). Changing this needs a migration and a
# full re-ingest, so it is deliberately not a casual knob. jina-embeddings-v3
# and voyage-4-lite both emit 1024 by default.
EMBED_DIMS = int(os.getenv("EMBED_DIMS", "1024"))

# Texts per request. Jina has no limit; Voyage allows 1000; Gemini caps at 100.
# 500 is safe for all providers and keeps each request under Jina's 100K TPM
# ceiling at ~200 tokens/text average.
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "500"))

# Seconds to wait between batches. Jina's 100K TPM means ~500 texts × 200 tokens
# = 100K tokens per batch, so one batch per minute at most on the free tier.
# A 62s pace keeps us safely under the window. Voyage and Gemini have their own
# limits but this value is conservative enough for all.
EMBED_PACE_SECONDS = float(os.getenv("EMBED_PACE_SECONDS", "62.0"))

QUERY = "RETRIEVAL_QUERY"
DOCUMENT = "RETRIEVAL_DOCUMENT"

# Voyage names the same idea "query" / "document".
_VOYAGE_INPUT_TYPE = {QUERY: "query", DOCUMENT: "document"}

# Jina uses "retrieval.query" / "retrieval.passage".
_JINA_TASK = {QUERY: "retrieval.query", DOCUMENT: "retrieval.passage"}


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
# VOYAGE PROVIDER
# ─────────────────────────────────────────────────────────────────────────────
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


def _voyage_encode(texts: list[str], api_key: str, task_type: str) -> list[list[float]]:
    """
    Embed via the Voyage AI REST API.

    Uses httpx (already a dependency) rather than the voyageai SDK, to avoid
    adding a package for one endpoint. input_type carries the same asymmetry as
    the Gemini path: a query and the document answering it are embedded with
    different prompts, which Voyage handles server-side when input_type is set.
    """
    if not api_key:
        raise EmbeddingError(
            "EMBED_PROVIDER=voyage needs an API key. Ingestion uses "
            "VOYAGE_API_KEY; queries use the caller's key."
        )

    import httpx

    payload = {
        "model": VOYAGE_EMBED_MODEL,
        "input": texts,
        "input_type": _VOYAGE_INPUT_TYPE.get(task_type, "document"),
        "output_dimension": EMBED_DIMS,
    }
    try:
        resp = httpx.post(
            VOYAGE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise EmbeddingError(f"Voyage request failed: {exc}") from exc

    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset-requests", "")
        hint = f" retryDelay: \"{retry_after}s\"" if retry_after else ""
        raise EmbeddingError(f"429 Voyage rate limit:{hint} {resp.text[:200]}")
    if resp.status_code >= 400:
        raise EmbeddingError(
            f"Voyage returned {resp.status_code}: {resp.text[:300]}"
        )

    data = resp.json().get("data", [])
    # The API preserves input order, but sort on the returned index to be
    # certain a batch is never silently misaligned with its texts.
    data.sort(key=lambda d: d.get("index", 0))
    vectors = [d["embedding"] for d in data]
    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"Voyage returned {len(vectors)} vectors for {len(texts)} texts"
        )
    return vectors


# ─────────────────────────────────────────────────────────────────────────────
# JINA PROVIDER
# ─────────────────────────────────────────────────────────────────────────────
JINA_URL = "https://api.jina.ai/v1/embeddings"
# Jina has its own auth separate from the BYOK Gemini key. The runtime path
# passes the user's Gemini key as `api_key`, which doesn't work with Jina;
# read the real key from the environment instead.
_JINA_API_KEY = os.getenv("JINA_API_KEY", "")


def _jina_encode(texts: list[str], api_key: str, task_type: str) -> list[list[float]]:
    """
    Embed via the Jina AI REST API (jina-embeddings-v3).

    Free tier: 10M tokens, no card required. 100 RPM / 100K TPM.
    No batch size limit. 1024-dim default, asymmetric retrieval.
    """
    key = _JINA_API_KEY or api_key
    if not key:
        raise EmbeddingError(
            "EMBED_PROVIDER=jina needs JINA_API_KEY. Get one free (no card) at jina.ai."
        )

    import httpx

    payload = {
        "model": JINA_EMBED_MODEL,
        "input": texts,
        "task": _JINA_TASK.get(task_type, "retrieval.passage"),
        "dimensions": EMBED_DIMS,
        "normalized": True,
        "embedding_type": "float",
    }
    try:
        resp = httpx.post(
            JINA_URL,
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=120.0,
        )
    except httpx.HTTPError as exc:
        raise EmbeddingError(f"Jina request failed: {exc}") from exc

    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after", "")
        hint = f" retryDelay: \"{retry_after}s\"" if retry_after else ""
        raise EmbeddingError(f"429 Jina rate limit:{hint} {resp.text[:200]}")
    if resp.status_code >= 400:
        raise EmbeddingError(
            f"Jina returned {resp.status_code}: {resp.text[:300]}"
        )

    data = resp.json().get("data", [])
    data.sort(key=lambda d: d.get("index", 0))
    vectors = [d["embedding"] for d in data]
    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"Jina returned {len(vectors)} vectors for {len(texts)} texts"
        )
    return vectors


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


def _is_transient_network(exc: BaseException) -> bool:
    m = str(exc).lower()
    return (
        "connection" in m or "timeout" in m or "reset" in m
        or "10054" in m or "eof" in m or "broken pipe" in m
    )


def _is_daily_quota(exc: BaseException) -> bool:
    """
    Distinguish the daily cap from the per-minute one.

    The free tier enforces BOTH, and a 429 can be either:

        EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier     1000/day
        EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier   100/min

    Only the per-minute one is worth waiting out. The daily one names itself,
    and waiting on it burns minutes to fail anyway, so it is raised, not
    retried. Anything else that is a 429 is treated as the per-minute limit.
    """
    m = str(exc).lower()
    # "perday" would also substring-match inside "...perminute..."? No; but be
    # explicit so a future message format cannot blur the two.
    return ("perday" in m or "per day" in m or "requestsperday" in m) and "perminute" not in m


def _retry_delay_seconds(exc: BaseException, fallback: float) -> float:
    """
    Pull the server's own retry hint out of a 429.

    Gemini returns it as either `retryDelay: "16s"` or a protobuf-ish
    `retry_delay { seconds: 16 }`. Honouring it is the difference between
    retrying at the right moment and retrying too early and failing again,
    which is exactly what a fixed 10s-first-wait did against a 16s hint.
    """
    m = str(exc)
    match = re.search(r"retry[_ ]?delay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)\s*s", m, re.I)
    if not match:
        match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", m, re.I)
    if match:
        return float(match.group(1))
    return fallback


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────
def encode_sync(texts: list[str], api_key: str = "", task_type: str = DOCUMENT) -> list[list[float]]:
    if not texts:
        return []
    if EMBED_PROVIDER == "local":
        return _local_encode(texts)
    if EMBED_PROVIDER == "jina":
        return _jina_encode(texts, api_key, task_type)
    if EMBED_PROVIDER == "voyage":
        return _voyage_encode(texts, api_key, task_type)
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

    TWO LIMITS, COUNTED DIFFERENTLY
    ───────────────────────────────
    The free tier enforces a daily cap and a per-minute cap, and they count
    different things:

      daily       1000 REQUESTS.  Batching 100 texts per request makes this a
                  non-issue: the whole corpus is a few dozen requests.
      per-minute  100 TEXTS.      One request of 100 texts spends the entire
                  minute, so the next request is denied instantly.

    That second point is the one that is easy to get wrong. Retrying does not
    help, because the batch already spent the minute. Pacing is what works:
    EMBED_PACE_SECONDS waits out the window between batches, holding throughput
    at ~100 texts/minute, which is the free tier's real ceiling.

    The retry below is a safety net for the ragged edge of the window, and it
    honours the server's `retryDelay` rather than a fixed schedule so it lands
    when the window has actually reopened. Daily exhaustion is raised, not
    retried. The caller's ingest is idempotent, so an interrupt resumes safely.
    """
    if not texts:
        return []
    if EMBED_PROVIDER == "local":
        return _local_encode(texts)

    # Per-request text cap: Jina has no limit; Voyage 1000; Gemini 100.
    provider_cap = 10_000 if EMBED_PROVIDER in ("jina", "voyage") else 100
    batch_size = max(1, min(batch_size, provider_cap))
    out: list[list[float]] = []

    i = 0
    while i < len(texts):
        batch = texts[i:i + batch_size]

        max_attempts = 12
        for attempt in range(max_attempts):
            try:
                out.extend(encode_sync(batch, api_key, DOCUMENT))
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
                is_rl = _is_rate_limit(exc)
                is_net = _is_transient_network(exc)
                if not is_rl and not is_net:
                    raise EmbeddingError(f"Embedding failed at item {i}: {exc}") from exc
                if attempt == max_attempts - 1:
                    raise EmbeddingError(
                        f"{'Rate limit' if is_rl else 'Network error'} at item {i} did not "
                        f"clear after {max_attempts} attempts. Re-run to resume; already-"
                        f"embedded files are skipped."
                    ) from exc
                if is_net:
                    wait = 5.0 + attempt * 3
                    logger.info(
                        "Network error at item %d (attempt %d/%d), retrying in %.0fs — %s",
                        i, attempt + 1, max_attempts, wait, exc,
                    )
                else:
                    hint = _retry_delay_seconds(exc, fallback=65.0)
                    wait = max(hint, 65.0) + attempt * 2
                    logger.info(
                        "Rate limited at item %d (attempt %d/%d), waiting %.0fs — %s",
                        i, attempt + 1, max_attempts, wait, exc,
                    )
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
    if EMBED_PROVIDER == "jina":
        return f"jina:{JINA_EMBED_MODEL} ({EMBED_DIMS}d, asymmetric)"
    if EMBED_PROVIDER == "voyage":
        return f"voyage:{VOYAGE_EMBED_MODEL} ({EMBED_DIMS}d, asymmetric)"
    return f"gemini:{GEMINI_EMBED_MODEL} ({EMBED_DIMS}d, asymmetric)"
