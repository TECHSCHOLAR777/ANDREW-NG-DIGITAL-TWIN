"""
routers/chat.py
─────────────────────────────────────────────────────────────────────────────
FastAPI chat router — integrates:
  • Hybrid RRF retrieval (pgvector + FTS via SQL function)
  • Vector-anchored graph traversal (2-hop CTE)
  • Gemini prompt caching (PromptCacheManager)
  • Async triplet extraction (TripletExtractor background task)

BYOK (Bring Your Own Key): API keys come from the request header
  X-Gemini-API-Key: <user_key>
  X-Tenant-ID: <uuid>

This keeps hosting cost at $0 — the developer's backend never stores or uses
its own API key for generation calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
import re
import os
import hashlib
from collections import deque
from typing import Annotated, Literal

import asyncpg
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
)
from fastapi.responses import Response, StreamingResponse
import httpx
from pydantic import BaseModel, Field

from ..services.triplet_extractor import TripletExtractor
from ..services.prompt_cache import PromptCacheManager, CachedGenerationRequest
from ..services import retrieval as rtv
from ..services import graph_memory as gmem
from ..services import routing
from ..services import persona as persona_mod
from ..services import streaming
from ..services import rate_limit
from ..services import curriculum as curr

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# Per-session cache manager (one per process; upgrade to Redis-backed for multi-pod)
_cache_managers: dict[str, PromptCacheManager] = {}
MAX_TTS_CHARS = int(os.getenv("MAX_TTS_CHARS", "1200"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
CHATTERBOX_URL = os.getenv("CHATTERBOX_URL", "http://127.0.0.1:5002/v1/audio/speech")


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY: DB pool from app state
# ─────────────────────────────────────────────────────────────────────────────
async def get_db(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY: Tenant identity (no Gemini key required)
# Used by endpoints that only read/write tenant data (graph, clear, tts).
# ─────────────────────────────────────────────────────────────────────────────
def get_tenant_id(
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=401, detail="X-Tenant-Id header required")
    try:
        uuid.UUID(x_tenant_id)  # validate UUID format
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a valid UUID")
    _enforce_rate_limit(x_tenant_id, "read", rate_limit.RATE_LIMIT_READ)
    return x_tenant_id


def _enforce_rate_limit(tenant_id: str, scope: str, per_minute: int) -> None:
    """Raise 429 with a Retry-After header when a tenant exceeds its budget."""
    allowed, retry_after = rate_limit.limiter.check(tenant_id, scope, per_minute)
    if allowed:
        return
    wait = max(1, int(retry_after) + 1)
    logger.warning("Rate limit hit: tenant=%s scope=%s", tenant_id, scope)
    raise HTTPException(
        status_code=429,
        detail=f"Too many requests. Try again in about {wait} second{'s' if wait != 1 else ''}.",
        headers={"Retry-After": str(wait)},
    )


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY: Extract and validate BYOK headers
# The server-side GEMINI_API_KEY fallback is a development convenience only.
# In production every request must carry the user's own key (true BYOK) —
# otherwise anonymous visitors would silently bill the server owner's key.
# ─────────────────────────────────────────────────────────────────────────────
def get_api_keys(
    x_gemini_api_key: Annotated[str | None, Header()] = None,
    x_tenant_id:      Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    tenant_id = get_tenant_id(x_tenant_id)
    # Generation is the expensive path, so it carries a tighter budget than
    # the read endpoints already charged by get_tenant_id.
    _enforce_rate_limit(tenant_id, "chat", rate_limit.RATE_LIMIT_CHAT)

    key = (x_gemini_api_key or "").strip()
    # Treat the UI placeholder / obviously invalid values as absent
    if key == "AIzaSy..." or len(key) < 10:
        key = ""

    if not key and ENVIRONMENT == "development":
        key = os.environ.get("GEMINI_API_KEY", "")

    if not key:
        raise HTTPException(
            status_code=401,
            detail="A Gemini API key is required. Enter your own key in the sidebar (sent as X-Gemini-Api-Key).",
        )

    return {"gemini_key": key, "tenant_id": tenant_id}


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST / RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
class TurnMessage(BaseModel):
    role:    Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=12000)

class ChatRequest(BaseModel):
    session_id:       str = Field(..., min_length=1, max_length=128)
    message:          str = Field(..., min_length=1, max_length=4000)
    turn_history:     list[TurnMessage] = Field(default_factory=list, max_length=20)
    query_embedding:  list[float] | None = Field(
        default=None,
        description=(
            "Optional pre-computed 768-dim embedding from all-mpnet-base-v2. "
            "If omitted the server computes it locally (no API call). Ignored "
            "when the query is rewritten, since the rewrite changes the text "
            "that must be embedded."
        )
    )
    temperature:      float = Field(default=0.7, ge=0.0, le=1.0)
    top_k_chunks:     int   = Field(default=10, ge=1, le=30)

class RetrievedChunk(BaseModel):
    chunk_id:     str
    source_file:  str
    source_type:  str
    chunk_text:   str
    final_score:  float
    vector_score: float = 0.0

class GraphNode(BaseModel):
    node_id:        str
    canonical_name: str
    node_type:      str
    hop_distance:   int
    combined_score: float

class ChatResponse(BaseModel):
    session_id:         str
    assistant_message:  str
    retrieved_chunks:   list[RetrievedChunk]
    graph_context:      list[GraphNode]
    turn_id:            str
    cache_status:       str    # "hit" | "miss" | "uncached"
    cached_token_count: int   = 0      # real figure from Gemini usage metadata
    retrieval_confidence: float = 0.0  # best cosine similarity among hits
    is_grounded:        bool  = True   # False => answered from general expertise
    query_used:         str   = ""     # rewritten query, when a rewrite happened


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
MAX_CACHE_MANAGERS = int(os.getenv("MAX_CACHE_MANAGERS", "128"))


def _get_cache_manager(gemini_key: str) -> PromptCacheManager:
    """
    Get or create a PromptCacheManager keyed by API key (user-scoped).

    Bounded with simple LRU eviction. This dictionary previously grew by one
    entry per distinct API key forever, which on a public deployment is a plain
    memory leak.
    """
    key_fingerprint = hashlib.sha256(gemini_key.encode("utf-8")).hexdigest()

    manager = _cache_managers.pop(key_fingerprint, None)
    if manager is None:
        manager = PromptCacheManager(gemini_key)

    _cache_managers[key_fingerprint] = manager   # reinsert marks as most recent

    while len(_cache_managers) > MAX_CACHE_MANAGERS:
        evicted_key, _ = next(iter(_cache_managers.items()))
        _cache_managers.pop(evicted_key, None)
        logger.info("Evicted a cache manager (limit %d reached)", MAX_CACHE_MANAGERS)

    return manager


# Embedding lives in services/retrieval.py now (dedicated thread pool, shared
# with the triplet extractor). Re-exported so main.py's startup hook is stable.
preload_local_embed_model = rtv.preload_embed_model


def _get_corpus_tenant_id() -> str | None:
    """Optional corpus owner. Leave unset to query all shared knowledge chunks."""
    raw = os.getenv("CORPUS_TENANT_ID", "").strip()
    if not raw:
        return None
    try:
        uuid.UUID(raw)
    except ValueError:
        logger.warning("Ignoring invalid CORPUS_TENANT_ID=%s", raw)
        return None
    return raw


async def _sweep_unprocessed_turns(
    db: asyncpg.Pool,
    tenant_id: str,
    gemini_key: str,
    limit: int = 3,
) -> None:
    """
    Re-run extraction for turns whose background task previously failed.

    Extraction can fail on a rate limit, a parse error, or a process restart.
    Those turns now correctly stay `triplets_extracted = FALSE` (fix F5), which
    makes them findable via the partial index built for exactly this purpose.

    The catch is BYOK: the server never stores anyone's API key, so a
    conventional cron sweeper would have no credentials to retry with. The
    resolution is to sweep opportunistically at the start of the same tenant's
    NEXT message, which is precisely when a valid key is in hand. Bounded to a
    few turns per request and run as a background task so it never delays a
    reply.
    """
    try:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, session_id, content, role
                FROM   conversation_turns
                WHERE  tenant_id = $1::uuid
                  AND  triplets_extracted = FALSE
                  AND  role = 'user'
                  AND  created_at < NOW() - INTERVAL '2 minutes'
                ORDER  BY created_at DESC
                LIMIT  $2
                """,
                uuid.UUID(tenant_id), limit,
            )

        if not rows:
            return

        logger.info("Sweeping %d unprocessed turn(s) for tenant %s", len(rows), tenant_id)
        extractor = TripletExtractor(db, gemini_key)

        for row in rows:
            # The paired assistant reply gives the extractor context for
            # judging whether the student actually understood.
            async with db.acquire() as conn:
                reply = await conn.fetchval(
                    """
                    SELECT content FROM conversation_turns
                    WHERE tenant_id = $1::uuid AND session_id = $2
                      AND role = 'assistant' AND turn_index > (
                          SELECT turn_index FROM conversation_turns WHERE id = $3
                      )
                    ORDER BY turn_index ASC LIMIT 1
                    """,
                    uuid.UUID(tenant_id), row["session_id"], row["id"],
                ) or ""

            await extractor.process_turn(
                tenant_id         = uuid.UUID(tenant_id),
                turn_id           = row["id"],
                user_content      = row["content"],
                assistant_content = reply,
                session_id        = row["session_id"],
            )
    except Exception as exc:  # noqa: BLE001 - recovery must never break a turn
        logger.warning("Unprocessed-turn sweep failed for tenant %s: %s", tenant_id, exc)


def _concepts_in_message(message: str, prereq_map: dict[str, set[str]]) -> set[str]:
    """
    Which curriculum concepts a message is about.

    Deliberately plain substring matching over known concept names rather than
    another embedding call. The curriculum is a few hundred names, the match
    has to be exact enough to justify pulling in extra material, and this runs
    on the critical path of every turn. A fuzzy match here would produce
    confident prerequisite injection for concepts the student never raised,
    which is worse than injecting nothing.
    """
    haystack = curr.normalise(message)
    if not haystack:
        return set()

    known = set(prereq_map) | {p for prereqs in prereq_map.values() for p in prereqs}
    found = set()
    for concept in known:
        # Word-boundary check, so "adam" does not match "adamant".
        if concept and re.search(rf"(^|\s){re.escape(concept)}($|\s)", haystack):
            found.add(concept)
    return found


async def _prepare_turn(
    db: asyncpg.Pool,
    body: "ChatRequest",
    tenant_id: str,
    gemini_key: str,
) -> dict:
    """
    Everything that happens before generation, shared by /message and /stream.

    Kept in one place deliberately: two endpoints that each rebuilt the
    retrieval, graph and calibration steps would drift apart, and the streaming
    path would quietly stop matching the documented pipeline.
    """
    turn_history_dicts = [t.model_dump() for t in body.turn_history]

    # Classify first, so effort matches what the message needs.
    plan = routing.classify_turn(body.message, has_history=bool(turn_history_dicts))
    logger.info("Turn classified as %s: %s", plan.kind, plan.reason)

    # Learner state and curriculum structure, loaded before retrieval so the
    # graph can influence WHAT gets retrieved rather than only being pasted
    # alongside it. This is the loop the two subsystems previously never
    # closed: they ran in parallel and their outputs were concatenated.
    live_edges = await gmem.fetch_live_subgraph(db, uuid.UUID(tenant_id))
    learner = curr.LearnerState.from_edges(live_edges)

    prerequisite_hints: list[str] = []
    gap_diagnosis: list[dict] = []
    if plan.retrieve and await curr.curriculum_is_loaded(db):
        prereq_map = await curr.load_prerequisites(db)
        if prereq_map:
            query_concepts = _concepts_in_message(body.message, prereq_map)
            hints = curr.retrieval_hints(query_concepts, learner, prereq_map)
            prerequisite_hints = hints["expand"]

            # Several separate struggles sharing one upstream cause is the
            # diagnosis a human tutor makes and a chatbot does not.
            for root, explains in curr.diagnose_gaps(learner, prereq_map)[:2]:
                gap_diagnosis.append({"concept": root, "explains": explains})

    if plan.retrieve:
        retrieval, embedding = await rtv.retrieve_context(
            db                    = db,
            # The CALLER's tenant. Retrieval returns shared corpus material
            # plus anything this tenant privately owns (migration 011).
            caller_tenant_id      = tenant_id,
            message               = body.message,
            turn_history          = turn_history_dicts,
            gemini_key            = gemini_key,
            top_k                 = min(plan.top_k, body.top_k_chunks),
            precomputed_embedding = body.query_embedding,
            prerequisite_hints    = prerequisite_hints,
        )
    else:
        retrieval = rtv.RetrievalResult(
            passages=[], ranked_rows=[], confidence=0.0,
            is_grounded=True,   # a greeting is not an ungrounded claim
            query_used=body.message, was_rewritten=False,
        )
        embedding = await rtv.compute_embedding(body.message, gemini_key)

    graph_rows = await _run_graph_traversal(db, tenant_id, embedding)
    graph_summary = await _build_graph_context_summary(db, tenant_id, body.session_id, graph_rows)

    # Calibration from the student's whole history, rather than asking the
    # model to infer their level from the current message alone.
    async with db.acquire() as conn:
        student_name = await gmem.resolve_student_name(conn, uuid.UUID(tenant_id))
    learner_profile = persona_mod.build_learner_profile(live_edges, student_name)

    if gap_diagnosis:
        # Stated as an observation rather than an instruction, so the tutor
        # decides whether raising it serves this particular question.
        lines = [
            f"{g['concept']} appears upstream of several things they are stuck "
            f"on ({', '.join(g['explains'][:3])})"
            for g in gap_diagnosis
        ]
        learner_profile += (
            " LIKELY ROOT CAUSE: " + "; ".join(lines) +
            ". If it fits naturally, address the underlying gap rather than "
            "only the surface question."
        )

    gen_request = CachedGenerationRequest(
        session_id      = body.session_id,
        user_message    = body.message,
        turn_history    = turn_history_dicts[-6:],
        graph_context   = graph_summary,
        knowledge_block = rtv.build_knowledge_block(retrieval) if plan.retrieve else "",
        learner_profile = learner_profile,
        turn_kind       = plan.kind,
        temperature     = body.temperature,
    )

    return {
        "plan": plan,
        "retrieval": retrieval,
        "graph_rows": graph_rows,
        "gen_request": gen_request,
        "gap_diagnosis": gap_diagnosis,
        "prerequisites_used": prerequisite_hints,
        "citations": [
            {
                "chunk_id":    str(r["chunk_id"]),
                "source_file": r["source_file"],
                "source_type": r["source_type"],
                "chunk_text":  r["chunk_text"][:600],
                "final_score": float(r["final_score"]),
                "vector_score": float(r["vector_score"] or 0.0),
            }
            for r in retrieval.ranked_rows
        ],
        "graph_context": [
            {
                "node_id":        str(r["node_id"]),
                "canonical_name": r["canonical_name"],
                "node_type":      r["node_type"],
                "hop_distance":   r["hop_distance"],
                "combined_score": float(r["combined_score"]),
            }
            for r in graph_rows
        ],
    }


async def _persist_turn(
    db: asyncpg.Pool,
    tenant_id: str,
    sess_uuid: uuid.UUID,
    turn_id: uuid.UUID,
    user_message: str,
    assistant_reply: str,
) -> None:
    """
    Write the user and assistant turns, and keep the session record current.

    turn_index is computed inside each INSERT rather than by a separate
    COUNT(*) followed by an insert. The old read-then-write pattern let two
    concurrent turns in one session claim the same index; migration 010 adds a
    unique index so a collision now fails loudly instead of silently corrupting
    the order of someone's history.
    """
    ten_uuid = uuid.UUID(tenant_id)
    async with db.acquire() as conn:
        async with conn.transaction():
            # Create the session row on first turn, and bump its activity time
            # on every turn so the sidebar can order by recency.
            await conn.execute(
                """
                INSERT INTO chat_sessions (id, tenant_id, title)
                VALUES ($1, $2, left(regexp_replace($3, '\\s+', ' ', 'g'), 60))
                ON CONFLICT (id) DO UPDATE SET updated_at = NOW()
                """,
                sess_uuid, ten_uuid, user_message,
            )

            next_index = """
                COALESCE((
                    SELECT MAX(turn_index) + 1 FROM conversation_turns
                    WHERE tenant_id = $2 AND session_id = $3
                ), 0)
            """
            await conn.execute(
                f"""
                INSERT INTO conversation_turns
                    (id, tenant_id, session_id, role, content, turn_index)
                VALUES ($1, $2, $3, $4, $5, {next_index})
                """,
                turn_id, ten_uuid, sess_uuid, "user", user_message,
            )
            await conn.execute(
                f"""
                INSERT INTO conversation_turns
                    (id, tenant_id, session_id, role, content, turn_index)
                VALUES ($1, $2, $3, $4, $5, {next_index})
                """,
                uuid.uuid4(), ten_uuid, sess_uuid, "assistant", assistant_reply,
            )


def _schedule_followups(
    background_tasks: BackgroundTasks,
    db: asyncpg.Pool,
    tenant_id: str,
    gemini_key: str,
    sess_uuid: uuid.UUID,
    turn_id: uuid.UUID,
    user_message: str,
    assistant_reply: str,
    plan,
) -> None:
    """Queue graph extraction, failed-turn recovery and weight decay."""
    if plan.extract_triples:
        extractor = TripletExtractor(db, gemini_key)
        background_tasks.add_task(
            extractor.process_turn,
            tenant_id         = uuid.UUID(tenant_id),
            turn_id           = turn_id,
            user_content      = user_message,
            assistant_content = assistant_reply,
            session_id        = sess_uuid,
        )
    else:
        # Greetings produce no beliefs worth storing. Mark them processed so
        # the recovery sweep does not keep retrying them forever.
        background_tasks.add_task(_mark_turn_skipped, db, turn_id)

    background_tasks.add_task(
        _sweep_unprocessed_turns,
        db=db, tenant_id=tenant_id, gemini_key=gemini_key,
    )
    background_tasks.add_task(gmem.maybe_run_decay, db)


async def _mark_turn_skipped(db: asyncpg.Pool, turn_id: uuid.UUID) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE conversation_turns SET triplets_extracted = TRUE WHERE id = $1",
            turn_id,
        )


async def _run_graph_traversal(
    db: asyncpg.Pool,
    tenant_id: str,
    embedding: list[float],
) -> list[asyncpg.Record]:
    """Call the vector_anchored_subgraph SQL function globally (no session limit)."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM vector_anchored_subgraph(
                $1::uuid,    -- tenant_id
                $2::vector,  -- query_embedding
                5,           -- top_k anchor nodes
                0.5,         -- cosine threshold
                NULL,        -- predicates
                NULL         -- global traversal (no session limit)
            )
            """,
            uuid.UUID(tenant_id),
            embedding,
        )
    return rows


async def _build_graph_context_summary(
    db: asyncpg.Pool,
    tenant_id: str,
    session_id: str,
    graph_nodes: list[asyncpg.Record],
) -> str:
    """
    Delegates to services/graph_memory.py.

    That module handles temporal filtering (only currently-believed edges),
    trajectory rendering for resolved difficulties, and sanitising evidence
    quotes before they reach the prompt.
    """
    return await gmem.build_graph_context_summary(
        db, tenant_id, _coerce_session_uuid(session_id), graph_nodes
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CHAT ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/message", response_model=ChatResponse)
async def chat_message(
    body:             ChatRequest,
    background_tasks: BackgroundTasks,
    db:               asyncpg.Pool = Depends(get_db),
    keys:             dict         = Depends(get_api_keys),
) -> ChatResponse:
    """
    Main chat endpoint. Pipeline:

    1. Compute query embedding (or use provided one).
    2. Parallel: hybrid chunk retrieval + graph traversal.
    3. Get/create prompt cache (persona + RAG chunks).
    4. Generate Gemini response using cached context.
    5. Save conversation turn to DB.
    6. Background: extract triplets from this turn.
    7. Return response immediately.
    """
    gemini_key = keys["gemini_key"]
    tenant_id  = keys["tenant_id"]
    turn_id    = uuid.uuid4()
    sess_uuid  = _coerce_session_uuid(body.session_id)

    # ── Step 0: Ensure tenant exists ───────────────────────────────────────
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            uuid.UUID(tenant_id), "Digital Twin User",
        )

    # ── Steps 1-3: routing, retrieval, graph memory, calibration ──────────
    ctx = await _prepare_turn(db, body, tenant_id, gemini_key)

    # ── Step 4: Generate ──────────────────────────────────────────────────
    cache_manager = _get_cache_manager(gemini_key)
    try:
        assistant_reply, cache_status = await cache_manager.generate(
            request        = ctx["gen_request"],
            gemini_api_key = gemini_key,
        )
    except Exception as e:
        err_msg = str(e)
        logger.exception("Generation failed: %s", e)
        if "429" in err_msg or "quota" in err_msg.lower() or "rate" in err_msg.lower():
            raise HTTPException(
                status_code=429,
                detail="Gemini API rate limit reached. The free tier allows ~20 requests/minute. Please wait a moment and try again.",
            )
        raise HTTPException(status_code=502, detail=f"Generation error: {err_msg}")

    # ── Step 5: Persist ───────────────────────────────────────────────────
    await _persist_turn(db, tenant_id, sess_uuid, turn_id, body.message, assistant_reply)

    # ── Step 6: Background work ───────────────────────────────────────────
    _schedule_followups(
        background_tasks, db, tenant_id, gemini_key, sess_uuid,
        turn_id, body.message, assistant_reply, ctx["plan"],
    )

    # ── Step 7: Return ────────────────────────────────────────────────────
    retrieval = ctx["retrieval"]
    return ChatResponse(
        session_id           = body.session_id,
        assistant_message    = assistant_reply,
        retrieved_chunks     = [RetrievedChunk(**c) for c in ctx["citations"]],
        graph_context        = [GraphNode(**g) for g in ctx["graph_context"]],
        turn_id              = str(turn_id),
        cache_status         = cache_status.status,
        cached_token_count   = cache_status.cached_tokens,
        retrieval_confidence = round(retrieval.confidence, 4),
        is_grounded          = retrieval.is_grounded,
        query_used           = retrieval.query_used if retrieval.was_rewritten else "",
    )


@router.post("/stream")
async def chat_message_stream(
    body:             ChatRequest,
    background_tasks: BackgroundTasks,
    db:               asyncpg.Pool = Depends(get_db),
    keys:             dict         = Depends(get_api_keys),
):
    """
    Same pipeline as /message, delivered as Server-Sent Events.

    Event types:
      meta      once, before generation: turn kind, grounding, citations
      delta     incremental text, for progressive rendering
      sentence  a COMPLETE sentence, the moment it is complete

    The `sentence` events are what make voice usable. Previously the client had
    to wait for the entire answer, then request TTS for each sentence in turn,
    which put first audio 8 to 30 seconds after the question. Emitting each
    sentence as it completes lets synthesis for sentence one start while
    sentence three is still being written.

      done      final text, turn id, cache telemetry
      error     failure, with a human-readable detail
    """
    gemini_key = keys["gemini_key"]
    tenant_id  = keys["tenant_id"]
    turn_id    = uuid.uuid4()
    sess_uuid  = _coerce_session_uuid(body.session_id)

    async def event_stream():
        try:
            ctx = await _prepare_turn(db, body, tenant_id, gemini_key)

            yield _sse("meta", {
                "turn_kind":            ctx["plan"].kind,
                "is_grounded":          ctx["retrieval"].is_grounded,
                "retrieval_confidence": round(ctx["retrieval"].confidence, 4),
                "query_used":           ctx["retrieval"].query_used if ctx["retrieval"].was_rewritten else "",
                "retrieved_chunks":     ctx["citations"],
            })

            cache_manager = _get_cache_manager(gemini_key)
            accumulator = streaming.SentenceAccumulator()
            sentence_index = 0

            async for fragment in cache_manager.stream(ctx["gen_request"], gemini_key):
                yield _sse("delta", {"text": fragment})
                for sentence in accumulator.push(fragment):
                    yield _sse("sentence", {"text": sentence, "index": sentence_index})
                    sentence_index += 1

            for sentence in accumulator.flush():
                yield _sse("sentence", {"text": sentence, "index": sentence_index})
                sentence_index += 1

            assistant_reply = accumulator.full_text.strip()

            # Same mechanical persona checks the non-streaming path applies.
            # Repair is only safe on the accumulated text, so the client may
            # have rendered a banned opener; the corrected text arrives in
            # `done` and the client replaces what it showed.
            violations = persona_mod.validate_response(assistant_reply)
            if violations:
                logger.info("Persona violations (stream): %s", persona_mod.violation_summary(violations))
                repaired = persona_mod.repair_response(assistant_reply)
                if repaired and len(persona_mod.validate_response(repaired)) < len(violations):
                    assistant_reply = repaired

            await _persist_turn(db, tenant_id, sess_uuid, turn_id, body.message, assistant_reply)
            _schedule_followups(
                background_tasks, db, tenant_id, gemini_key, sess_uuid,
                turn_id, body.message, assistant_reply, ctx["plan"],
            )

            yield _sse("done", {
                "assistant_message": assistant_reply,
                "turn_id":           str(turn_id),
                "session_id":        body.session_id,
                "cache_status":      "streamed",
                "graph_context":     ctx["graph_context"],
            })

        except Exception as exc:  # noqa: BLE001
            logger.exception("Streaming generation failed: %s", exc)
            detail = str(exc)
            if "429" in detail or "quota" in detail.lower():
                detail = "Gemini API rate limit reached. Please wait a moment and try again."
            yield _sse("error", {"detail": detail})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx and several PaaS proxies buffer responses by default, which
            # would defeat the entire point of streaming.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class TTSRequest(BaseModel):
    text:  str   = Field(..., min_length=1, max_length=4000)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


# Cached reachability of the TTS service. The cloned voice typically runs on an
# ephemeral GPU session (see notebooks/kaggle_tts_server.py) whose tunnel dies
# when the session expires, so the client needs to know whether to expect a
# cloned voice or fall back to browser speech. Cached because probing upstream
# on every request would add a round trip to something that changes rarely.
_tts_status_cache: dict[str, float | bool] = {"checked_at": 0.0, "available": False}
_TTS_STATUS_TTL = 30.0


@router.get("/tts/status")
async def tts_status() -> dict:
    """
    Whether the cloned-voice service is reachable right now.

    The frontend uses this to choose between the cloned voice and the browser's
    built-in speech synthesis, so voice keeps working when the GPU session is
    down rather than failing silently.
    """
    import time as _time

    now = _time.monotonic()
    if now - float(_tts_status_cache["checked_at"]) < _TTS_STATUS_TTL:
        return {"available": bool(_tts_status_cache["available"]), "cached": True}

    available = False
    health_url = CHATTERBOX_URL.replace("/v1/audio/speech", "/health")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(health_url)
            available = resp.status_code == 200
    except Exception:  # noqa: BLE001 - unreachable is a normal state here
        available = False

    _tts_status_cache["checked_at"] = now
    _tts_status_cache["available"] = available
    return {"available": available, "cached": False}


@router.post("/tts")
async def synthesize_tts(
    body:      TTSRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> Response:
    """
    Synthesize text-to-speech via the Chatterbox service (CHATTERBOX_URL).

    POST with a JSON body (not GET with a query string) so spoken text does
    not land in access logs / browser history. Requires a tenant header so
    the endpoint is not an anonymous compute sink.

    The upstream response is fully buffered before returning: Chatterbox
    generates the complete file anyway, and this lets errors surface as real
    HTTP status codes instead of a truncated audio stream.
    """
    _enforce_rate_limit(tenant_id, "tts", rate_limit.RATE_LIMIT_TTS)

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    if len(text) > MAX_TTS_CHARS:
        raise HTTPException(status_code=413, detail=f"Text must be {MAX_TTS_CHARS} characters or fewer")

    payload = {
        "model": "tts-1",
        "input": text,
        "voice": "andrew_ng_ref",
        # Applied at synthesis rather than by changing playback rate, which
        # would shift pitch and formants on a cloned voice.
        "speed": body.speed,
    }

    # Read at call time, not import time. The cloned voice usually runs on an
    # ephemeral GPU session whose tunnel URL changes on every restart, so
    # picking the value up per request means a process manager that refreshes
    # the environment does not need a code change.
    tts_url = os.getenv("CHATTERBOX_URL", CHATTERBOX_URL)

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(tts_url, json=payload)
        except httpx.RequestError as exc:
            logger.error("Failed to reach TTS server at %s: %s", tts_url, exc)
            raise HTTPException(status_code=502, detail="TTS service is unavailable or timed out")

    if response.status_code != 200:
        logger.error("TTS upstream error: status %d, detail: %s", response.status_code, response.text[:300])
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: status {response.status_code}")

    return Response(content=response.content, media_type="audio/wav")


class TripletRow(BaseModel):
    node_id:         str
    canonical_name:  str
    node_type:       str
    metadata:        dict = Field(default_factory=dict)
    # hop_distance means "graph hops from the anchor set" in both places it is
    # produced, but the anchor differs by endpoint: /message anchors on the
    # nodes matched by query similarity, /graph anchors on the Student node.
    # score_basis says which, so a reader is never guessing what the number in
    # front of them measures.
    hop_distance:    int
    path_weight:     float
    vector_score:    float
    combined_score:  float
    score_basis:     str = "vector_anchored"   # or "student_distance"
    predicates_path: list[str] = Field(default_factory=list)

class EdgeRow(BaseModel):
    id:            str
    subject_id:    str
    predicate:     str
    object_id:     str
    weight:        float
    evidence:      str
    observation_count: int = 1

class GraphPayload(BaseModel):
    nodes: list[TripletRow]
    edges: list[EdgeRow]


# ── Graph data endpoint (for React Flow visualization) ────────────────────────
@router.get("/graph/{session_id}", response_model=GraphPayload)
async def get_session_graph(
    session_id: str,
    view:       str = "session",   # "session" or "global"
    db:         asyncpg.Pool = Depends(get_db),
    tenant_id:  str          = Depends(get_tenant_id),
) -> GraphPayload:
    """
    Return the session or global knowledge graph (nodes + edges).
    Used by the React Flow visualizer component.
    Requires only the tenant header — no Gemini key (nothing here calls Gemini).
    """
    session_uuid = _coerce_session_uuid(session_id)
    if view not in {"session", "global"}:
        raise HTTPException(status_code=400, detail="view must be 'session' or 'global'")

    async with db.acquire() as conn:
        # Exclude 'named' and 'is' predicates from visualization — these are
        # metadata edges (Student→name, Student→role) used for identity resolution.
        # They create redundant nodes; the student's name is already shown on
        # the Student node via the resolved_student_name subquery.
        if view == "global":
            edge_rows = await conn.fetch(
                """
                SELECT id, subject_id, predicate, object_id, weight, coalesce(evidence, '') as evidence,
                       coalesce(observation_count, 1) as observation_count
                FROM relation_edges
                WHERE tenant_id = $1::uuid
                  AND invalidated_at IS NULL
                  AND predicate NOT IN ('named', 'is')
                ORDER BY weight DESC
                LIMIT 150
                """,
                uuid.UUID(tenant_id),
            )
        else:
            edge_rows = await conn.fetch(
                """
                SELECT id, subject_id, predicate, object_id, weight, coalesce(evidence, '') as evidence,
                       coalesce(observation_count, 1) as observation_count
                FROM relation_edges
                WHERE tenant_id = $1::uuid AND session_id = $2::uuid
                  AND invalidated_at IS NULL
                  AND predicate NOT IN ('named', 'is')
                ORDER BY weight DESC
                LIMIT 150
                """,
                uuid.UUID(tenant_id),
                session_uuid,
            )

        # Collect exact node IDs connected by these edges
        node_ids = set()
        for r in edge_rows:
            node_ids.add(r["subject_id"])
            node_ids.add(r["object_id"])

        if node_ids:
            # The resolved_student_name subquery still queries 'named'/'is' edges
            # in relation_edges — we just don't show them as graph edges.
            node_rows = await conn.fetch(
                """
                SELECT en.id, en.canonical_name, en.node_type, en.metadata,
                       (
                           SELECT en_name.canonical_name
                           FROM relation_edges re_name
                           JOIN entity_nodes en_name ON en_name.id = re_name.object_id
                           WHERE re_name.tenant_id = $1::uuid 
                             AND re_name.subject_id = en.id
                             AND re_name.predicate IN ('named', 'is')
                           LIMIT 1
                       ) AS resolved_student_name
                FROM entity_nodes en
                WHERE en.tenant_id = $1::uuid AND en.id = ANY($2::uuid[])
                """,
                uuid.UUID(tenant_id),
                list(node_ids),
            )
        else:
            node_rows = []

    # ── Compute hop_distance via BFS from Student nodes ───────────────────
    # Build adjacency list from edges (undirected for hop counting)
    adjacency: dict[str, set[str]] = {}
    edge_weights: dict[str, float] = {}  # node_id → max edge weight
    for r in edge_rows:
        sid = str(r["subject_id"])
        oid = str(r["object_id"])
        adjacency.setdefault(sid, set()).add(oid)
        adjacency.setdefault(oid, set()).add(sid)
        w = float(r["weight"])
        edge_weights[sid] = max(edge_weights.get(sid, 0.0), w)
        edge_weights[oid] = max(edge_weights.get(oid, 0.0), w)

    # Find Student nodes as BFS roots (hop 0)
    node_type_map = {str(row["id"]): row["node_type"] for row in node_rows}
    student_ids = {nid for nid, nt in node_type_map.items() if nt == "Student"}

    hop_distances: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()
    for sid in student_ids:
        hop_distances[sid] = 0
        queue.append((sid, 0))

    while queue:
        current, depth = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in hop_distances:
                hop_distances[neighbor] = depth + 1
                queue.append((neighbor, depth + 1))

    # Nodes unreachable from any Student get hop = 1 (direct concept)
    for nid in node_type_map:
        if nid not in hop_distances:
            hop_distances[nid] = 1

    nodes = []
    for row in node_rows:
        node_type = row["node_type"]
        nid = str(row["id"])
        hop = hop_distances.get(nid, 1)
        # Score: Student=1.0, then decay by hop, boosted by edge weight
        max_w = edge_weights.get(nid, 0.5)
        score = 1.0 if node_type == "Student" else round(
            min(1.0, max_w * (0.9 ** hop)), 3
        )
        # Rename "Student" canonical label to a user-friendly name if they have one
        canonical_name = row["canonical_name"]
        if node_type == "Student":
            canonical_name = row["resolved_student_name"] or "You"

        nodes.append(
            TripletRow(
                node_id        = nid,
                canonical_name = canonical_name,
                node_type      = node_type,
                metadata       = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"] or {},
                hop_distance   = hop,
                path_weight    = score,
                vector_score   = score,
                combined_score = score,
                # This endpoint has no query to compare against, so the score
                # is edge-weight decayed by distance from the student, not a
                # similarity. Saying so prevents the two different meanings of
                # this field from being silently conflated.
                score_basis    = "student_distance",
                predicates_path= []
            )
        )

    edges = []
    for row in edge_rows:
        edges.append(
            EdgeRow(
                id         = str(row["id"]),
                subject_id = str(row["subject_id"]),
                predicate  = row["predicate"],
                object_id  = str(row["object_id"]),
                weight     = float(row["weight"]),
                # Sanitised before it leaves the API: this text is user-authored
                # and ends up rendered in a browser and in prompts.
                evidence   = gmem.sanitize_evidence(row["evidence"]),
                observation_count = int(row["observation_count"] or 1),
            )
        )

    return GraphPayload(nodes=nodes, edges=edges)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION PERSISTENCE
# The backend has always written every turn to conversation_turns and never
# read them back, so a browser refresh destroyed conversations that were
# sitting safely in Postgres the whole time. These endpoints close that loop.
# ─────────────────────────────────────────────────────────────────────────────
class SessionSummary(BaseModel):
    id:            str
    title:         str
    updated_at:    str
    message_count: int


class StoredMessage(BaseModel):
    role:    Literal["user", "assistant"]
    content: str


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    db:        asyncpg.Pool = Depends(get_db),
    tenant_id: str          = Depends(get_tenant_id),
    limit:     int          = 50,
) -> list[SessionSummary]:
    """This tenant's conversations, most recently active first."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.title, s.updated_at,
                   (SELECT COUNT(*) FROM conversation_turns ct
                     WHERE ct.session_id = s.id AND ct.tenant_id = s.tenant_id) AS message_count
            FROM   chat_sessions s
            WHERE  s.tenant_id = $1::uuid
            ORDER  BY s.updated_at DESC
            LIMIT  $2
            """,
            uuid.UUID(tenant_id), max(1, min(limit, 200)),
        )

    return [
        SessionSummary(
            id            = str(r["id"]),
            title         = r["title"],
            updated_at    = r["updated_at"].isoformat(),
            message_count = int(r["message_count"]),
        )
        for r in rows
    ]


@router.get("/sessions/{session_id}/messages", response_model=list[StoredMessage])
async def get_session_messages(
    session_id: str,
    db:         asyncpg.Pool = Depends(get_db),
    tenant_id:  str          = Depends(get_tenant_id),
) -> list[StoredMessage]:
    """Full transcript for one conversation, in order."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content
            FROM   conversation_turns
            WHERE  tenant_id = $1::uuid AND session_id = $2::uuid
            ORDER  BY turn_index ASC
            """,
            uuid.UUID(tenant_id), _coerce_session_uuid(session_id),
        )
    return [StoredMessage(role=r["role"], content=r["content"]) for r in rows]


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db:         asyncpg.Pool = Depends(get_db),
    tenant_id:  str          = Depends(get_tenant_id),
) -> dict[str, str]:
    """
    Delete one conversation and the graph edges it produced.

    Entity nodes are deliberately left alone: they are shared across sessions,
    so removing them would tear holes in conversations the user did not delete.
    """
    sess_uuid = _coerce_session_uuid(session_id)
    ten_uuid = uuid.UUID(tenant_id)
    async with db.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM relation_edges WHERE tenant_id = $1 AND session_id = $2",
                ten_uuid, sess_uuid,
            )
            await conn.execute(
                "DELETE FROM conversation_turns WHERE tenant_id = $1 AND session_id = $2",
                ten_uuid, sess_uuid,
            )
            await conn.execute(
                "DELETE FROM chat_sessions WHERE tenant_id = $1 AND id = $2",
                ten_uuid, sess_uuid,
            )
    return {"status": "ok", "message": "Conversation deleted."}


@router.get("/graph/{session_id}/status")
async def graph_extraction_status(
    session_id: str,
    db:         asyncpg.Pool = Depends(get_db),
    tenant_id:  str          = Depends(get_tenant_id),
) -> dict[str, int]:
    """
    How many turns in this session are still awaiting graph extraction.

    Exists so the client can stop guessing. It previously refreshed the graph on
    blind five and twelve second timers, which either fired before extraction
    finished or wasted a request after it had. This is a cheap count the client
    can poll briefly and then stop.
    """
    async with db.acquire() as conn:
        pending = await conn.fetchval(
            """
            SELECT COUNT(*) FROM conversation_turns
            WHERE  tenant_id = $1::uuid AND session_id = $2::uuid
              AND  triplets_extracted = FALSE
            """,
            uuid.UUID(tenant_id), _coerce_session_uuid(session_id),
        )
    return {"pending_extractions": int(pending or 0)}


# ─────────────────────────────────────────────────────────────────────────────
# CURRICULUM
# The graph stops being a record of conversation and becomes a map of the
# subject, with the student's state overlaid on it.
# ─────────────────────────────────────────────────────────────────────────────
class PathStep(BaseModel):
    name:         str
    display_name: str
    difficulty:   str
    status:       str            # "mastered" | "struggling" | "new"
    source_files: list[str] = Field(default_factory=list)


class LearningPathResponse(BaseModel):
    target:      str
    available:   bool            # False when no curriculum has been built
    steps:       list[PathStep]
    already_known: int
    gaps:        list[dict] = Field(default_factory=list)


@router.get("/curriculum/path", response_model=LearningPathResponse)
async def get_learning_path(
    target:    str,
    db:        asyncpg.Pool = Depends(get_db),
    tenant_id: str          = Depends(get_tenant_id),
) -> LearningPathResponse:
    """
    What this student should learn, in order, to reach a target concept.

    This is a topological sort over the prerequisite DAG with everything the
    student has already mastered pruned out, which means the same target
    produces a short path for an advanced learner and a long one for a
    beginner. It is a computation over data, not a model guessing at a
    syllabus, so it is the same answer every time and can be checked.

    Degrades honestly: with no curriculum built, `available` is false and the
    caller shows nothing rather than inventing a path.
    """
    if not await curr.curriculum_is_loaded(db):
        return LearningPathResponse(
            target=target, available=False, steps=[], already_known=0
        )

    prereq_map = await curr.load_prerequisites(db)
    live_edges = await gmem.fetch_live_subgraph(db, uuid.UUID(tenant_id))
    learner = curr.LearnerState.from_edges(live_edges)

    ordered = curr.learning_path(target, learner, prereq_map)
    details = await curr.concept_details(db, ordered)

    steps = [
        PathStep(
            name=name,
            display_name=(details.get(name) or {}).get("display_name", name.title()),
            difficulty=(details.get(name) or {}).get("difficulty", "applied"),
            status="struggling" if name in learner.struggling else "new",
            source_files=(details.get(name) or {}).get("source_files", []),
        )
        for name in ordered
    ]

    full = curr.topological_order({curr.normalise(target)}, prereq_map)
    gaps = [
        {"concept": root, "explains": explains}
        for root, explains in curr.diagnose_gaps(learner, prereq_map)[:3]
    ]

    return LearningPathResponse(
        target=target,
        available=True,
        steps=steps,
        already_known=max(0, len(full) - len(ordered)),
        gaps=gaps,
    )


@router.delete("/graph/edge/{edge_id}")
async def invalidate_graph_edge(
    edge_id:   str,
    reason:    str = "corrected by student",
    db:        asyncpg.Pool = Depends(get_db),
    tenant_id: str          = Depends(get_tenant_id),
) -> dict[str, str]:
    """
    Retract one belief from the student's graph.

    Every edge is a guess a language model made about what someone meant, and
    some are wrong. Until now the only remedy was wiping all memory, so a
    single bad extraction shaped retrieval and future extraction forever.

    This is a soft delete (sets invalidated_at) rather than a DELETE for two
    reasons: history stays readable as a trajectory, and a student saying "that
    is wrong" is the cheapest labelled data available for evaluating the
    extraction prompt. Throwing the row away throws that signal away.
    """
    try:
        edge_uuid = uuid.UUID(edge_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="edge_id must be a valid UUID")

    async with db.acquire() as conn:
        ok = await conn.fetchval(
            "SELECT invalidate_edge_by_id($1::uuid, $2::uuid, $3)",
            uuid.UUID(tenant_id), edge_uuid, reason[:200],
        )

    if not ok:
        raise HTTPException(status_code=404, detail="Edge not found, or already retracted")

    logger.info("Tenant %s retracted edge %s", tenant_id, edge_id)
    return {"status": "ok", "message": "That connection has been removed from your memory graph."}


@router.post("/clear")
async def clear_tenant_memory(
    db:        asyncpg.Pool = Depends(get_db),
    tenant_id: str          = Depends(get_tenant_id),
) -> dict[str, str]:
    """
    Delete this tenant's learning memory: conversation turns, relation edges,
    entity aliases and entity nodes.

    Deliberately does NOT delete the tenant row itself, and never touches
    knowledge_chunks. The old implementation deleted the tenant row and let
    ON DELETE CASCADE fan out — which meant a request naming the shared
    corpus tenant could wipe the entire ingested corpus. The corpus tenant
    is additionally refused outright.
    """
    corpus_tenant = _get_corpus_tenant_id()
    if corpus_tenant and tenant_id == corpus_tenant:
        raise HTTPException(status_code=403, detail="The shared corpus tenant cannot be cleared.")

    ten_uuid = uuid.UUID(tenant_id)
    async with db.acquire() as conn:
        async with conn.transaction():
            # Order matters for FK integrity: edges reference nodes.
            await conn.execute("DELETE FROM relation_edges     WHERE tenant_id = $1", ten_uuid)
            await conn.execute("DELETE FROM entity_aliases     WHERE tenant_id = $1", ten_uuid)
            await conn.execute("DELETE FROM entity_nodes       WHERE tenant_id = $1", ten_uuid)
            await conn.execute("DELETE FROM conversation_turns WHERE tenant_id = $1", ten_uuid)
    logger.info("Cleared learning memory for tenant %s", tenant_id)
    return {"status": "ok", "message": "Tenant learning memory cleared successfully."}


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


def _coerce_session_uuid(session_id: str) -> uuid.UUID:
    """Accept stable frontend UUIDs and safely coerce legacy string session IDs."""
    try:
        return uuid.UUID(session_id)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"andrew-ng-session:{session_id}")
