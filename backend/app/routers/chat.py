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
from collections import deque
from typing import Annotated

import asyncpg
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
)
from fastapi.responses import StreamingResponse
import httpx
from pydantic import BaseModel, Field

from ..services.triplet_extractor import TripletExtractor
from ..services.prompt_cache import PromptCacheManager, CachedGenerationRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# Per-session cache manager (one per process; upgrade to Redis-backed for multi-pod)
_cache_managers: dict[str, PromptCacheManager] = {}


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY: DB pool from app state
# ─────────────────────────────────────────────────────────────────────────────
async def get_db(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY: Extract and validate BYOK headers
# ─────────────────────────────────────────────────────────────────────────────
def get_api_keys(
    x_gemini_api_key: Annotated[str | None, Header()] = None,
    x_tenant_id:      Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    # Fallback to .env key if UI key is missing or looks like a placeholder
    if not x_gemini_api_key or x_gemini_api_key == "AIzaSy..." or len(x_gemini_api_key) < 10:
        x_gemini_api_key = os.environ.get("GEMINI_API_KEY")
        
    if not x_gemini_api_key:
        raise HTTPException(status_code=401, detail="X-Gemini-Api-Key header required and not found in .env")
        
    if not x_tenant_id:
        raise HTTPException(status_code=401, detail="X-Tenant-Id header required")
    try:
        uuid.UUID(x_tenant_id)  # validate UUID format
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a valid UUID")
    return {"gemini_key": x_gemini_api_key, "tenant_id": x_tenant_id}


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST / RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
class TurnMessage(BaseModel):
    role:    str  # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    session_id:       str
    message:          str = Field(..., min_length=1, max_length=4000)
    turn_history:     list[TurnMessage] = Field(default_factory=list)
    query_embedding:  list[float] | None = Field(
        default=None,
        description=(
            "Pre-computed query embedding from text-embedding-004. "
            "If omitted, the server will compute it (costs one API call)."
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
    cache_status:       str   # "hit" | "miss" | "disabled"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _get_cache_manager(gemini_key: str) -> PromptCacheManager:
    """Get or create a PromptCacheManager keyed by API key (user-scoped)."""
    if gemini_key not in _cache_managers:
        _cache_managers[gemini_key] = PromptCacheManager(gemini_key)
    return _cache_managers[gemini_key]


_local_embed_model = None

def _get_local_embed_model():
    global _local_embed_model
    if _local_embed_model is None:
        from sentence_transformers import SentenceTransformer
        _local_embed_model = SentenceTransformer("all-mpnet-base-v2")
    return _local_embed_model


def preload_local_embed_model():
    """Warms up the sentence-transformers model to avoid delay on first request."""
    logger.info("Preloading sentence-transformers model...")
    _get_local_embed_model()
    logger.info("Sentence-transformers model loaded.")



async def _compute_embedding(
    text: str, gemini_key: str
) -> list[float]:
    """Compute a 768-dim embedding locally using sentence-transformers."""
    loop = asyncio.get_event_loop()
    model = _get_local_embed_model()
    result = await loop.run_in_executor(
        None,
        lambda: model.encode(text).tolist()
    )
    return result


async def _run_hybrid_retrieval(
    db: asyncpg.Pool,
    tenant_id: str,
    embedding: list[float],
    query_text: str,
    top_k: int,
) -> list[asyncpg.Record]:
    """Call the hybrid_chunk_retrieval SQL function."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM hybrid_chunk_retrieval(
                $1::uuid,     -- tenant_id
                $2::vector,   -- query_embedding
                $3,           -- query_text
                $4,           -- top_k
                60,           -- rrf_k (standard)
                0.65,         -- vector_weight
                0.35          -- fts_weight
            )
            """,
            uuid.UUID(tenant_id),
            embedding,       # asyncpg passes Python list as vector
            query_text,
            top_k,
        )
    return rows


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
    current_session_id: str,
    graph_nodes: list[asyncpg.Record],
) -> str:
    """
    Convert global graph traversal results (across all chat sessions under the same tenant)
    into a structured text summary, prioritizing active session relationships first,
    followed by past memory recall from other sessions.
    """
    node_uuids = [row["node_id"] for row in graph_nodes]
    if not node_uuids:
        return "No prior knowledge graph data available for this student."

    sess_uuid = uuid.UUID(current_session_id)
    ten_uuid = uuid.UUID(tenant_id)

    async with db.acquire() as conn:
        # 1. Look up student name globally under this tenant
        student_name = await conn.fetchval(
            """
            SELECT en_obj.canonical_name
            FROM relation_edges re
            JOIN entity_nodes en_sub ON en_sub.id = re.subject_id
            JOIN entity_nodes en_obj ON en_obj.id = re.object_id
            WHERE re.tenant_id = $1::uuid
              AND re.predicate = 'named'
              AND en_sub.node_type = 'Student'
            LIMIT 1
            """,
            ten_uuid
        )

        # 2. Get relation edges touching our traversed nodes
        edge_rows = await conn.fetch(
            """
            SELECT re.session_id, re.predicate, re.weight, COALESCE(re.evidence, '') as evidence,
                   en_sub.canonical_name as subject_name, en_sub.node_type as subject_type,
                   en_obj.canonical_name as object_name, en_obj.node_type as object_type
            FROM relation_edges re
            JOIN entity_nodes en_sub ON en_sub.id = re.subject_id
            JOIN entity_nodes en_obj ON en_obj.id = re.object_id
            WHERE re.tenant_id = $1::uuid
              AND (re.subject_id = ANY($2::uuid[]) OR re.object_id = ANY($2::uuid[]))
            ORDER BY re.weight DESC, re.created_at DESC
            LIMIT 100
            """,
            ten_uuid,
            node_uuids
        )

    active_lines = []
    past_lines = []
    seen = set()

    for row in edge_rows:
        sub = row["subject_name"]
        if row["subject_type"] == "Student" and student_name:
            sub = student_name
        obj = row["object_name"]
        if row["object_type"] == "Student" and student_name:
            obj = student_name
        
        pred = row["predicate"]
        key = (sub, pred, obj)
        if key in seen:
            continue
        seen.add(key)

        evidence = row["evidence"].strip()
        ev_str = f" (Evidence: \"{evidence}\")" if evidence else ""
        line = f"- {sub} -[{pred}]-> {obj}{ev_str}"

        # If session_id matches, it's active context. If session_id is NULL or different, it's past memory
        if row["session_id"] == sess_uuid:
            active_lines.append(line)
        else:
            past_lines.append(line)

    lines = []
    if student_name:
        lines.append(f"STUDENT PROFILE: Name is {student_name}.")
    else:
        lines.append("STUDENT PROFILE: Name is unknown.")

    lines.append("\nACTIVE SESSION RELATIONSHIPS (Focus on these topics in the current discussion):")
    if active_lines:
        lines.extend(active_lines)
    else:
        lines.append("- (No active session relationships recorded yet for these concepts)")

    lines.append("\nPAST MEMORY RECALL (Recalled from other chat sessions - use zero-shot memory to personalize):")
    if past_lines:
        lines.extend(past_lines)
    else:
        lines.append("- (No past memory relationships found for these concepts)")
    
    return "\n".join(lines)



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

    # ── Step 0: Ensure Tenant Exists ───────────────────────────────────────
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tenants (id, name)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            uuid.UUID(tenant_id),
            "Digital Twin User"
        )

    # ── Step 1: Embedding ──────────────────────────────────────────────────
    if body.query_embedding and len(body.query_embedding) == 768:
        embedding = body.query_embedding
    else:
        embedding = await _compute_embedding(body.message, gemini_key)

    # ── Step 2: Parallel retrieval (session-scoped) ────────────────────────
    chunk_rows, graph_rows = await asyncio.gather(
        _run_hybrid_retrieval(db, tenant_id, embedding, body.message, body.top_k_chunks),
        _run_graph_traversal(db, tenant_id, embedding),
    )

    chunk_texts = [row["chunk_text"] for row in chunk_rows]
    graph_summary = await _build_graph_context_summary(db, tenant_id, body.session_id, graph_rows)

    # ── Step 3 & 4: Cache + Generate ──────────────────────────────────────
    cache_manager = _get_cache_manager(gemini_key)
    cache_status  = "miss"

    try:
        session_cache = await cache_manager.get_or_create_cache(
            session_id = body.session_id,
            rag_chunks = chunk_texts,
        )
        cache_status = "hit" if session_cache.age_minutes > 0.1 else "miss"

        gen_request = CachedGenerationRequest(
            session_id   = body.session_id,
            user_message = body.message,
            turn_history = [t.model_dump() for t in body.turn_history[-6:]],  # last 6 turns
            graph_context= graph_summary,
            temperature  = body.temperature,
        )

        assistant_reply = await cache_manager.generate_with_cache(
            request    = gen_request,
            gemini_api_key = gemini_key,
            rag_chunks = chunk_texts,
        )

    except Exception as e:
        err_msg = str(e)
        logger.exception("Generation failed: %s", e)
        # Return 429 for rate-limit errors so the frontend can show a friendly message
        if "429" in err_msg or "quota" in err_msg.lower() or "rate" in err_msg.lower():
            raise HTTPException(
                status_code=429,
                detail="Gemini API rate limit reached. The free tier allows ~20 requests/minute. Please wait a moment and try again.",
            )
        raise HTTPException(status_code=502, detail=f"Generation error: {err_msg}")

    # ── Step 5: Persist conversation turn ─────────────────────────────────
    async with db.acquire() as conn:
        sess_uuid = (
            uuid.UUID(body.session_id) if _is_valid_uuid(body.session_id)
            else uuid.uuid5(uuid.NAMESPACE_DNS, body.session_id)
        )
        # Get current turn count for this session
        turn_count = await conn.fetchval(
            "SELECT COUNT(*) FROM conversation_turns WHERE session_id = $1",
            sess_uuid,
        ) or 0

        async with conn.transaction():
            # User turn
            await conn.execute(
                """
                INSERT INTO conversation_turns
                    (id, tenant_id, session_id, role, content, turn_index)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                turn_id,
                uuid.UUID(tenant_id),
                sess_uuid,
                "user",
                body.message,
                turn_count,
            )
            # Assistant turn
            await conn.execute(
                """
                INSERT INTO conversation_turns
                    (id, tenant_id, session_id, role, content, turn_index)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid.uuid4(),
                uuid.UUID(tenant_id),
                sess_uuid,
                "assistant",
                assistant_reply,
                turn_count + 1,
            )

    # ── Step 6: Background triplet extraction ─────────────────────────────
    extractor = TripletExtractor(db, gemini_key)
    background_tasks.add_task(
        extractor.process_turn,
        tenant_id       = uuid.UUID(tenant_id),
        turn_id         = turn_id,
        user_content    = body.message,
        assistant_content = assistant_reply,
        session_id      = uuid.UUID(body.session_id),
    )

    # ── Step 7: Return ─────────────────────────────────────────────────────
    return ChatResponse(
        session_id        = body.session_id,
        assistant_message = assistant_reply,
        retrieved_chunks  = [
            RetrievedChunk(
                chunk_id    = str(row["chunk_id"]),
                source_file = row["source_file"],
                source_type = row["source_type"],
                chunk_text  = row["chunk_text"][:200] + "...",  # truncate for response
                final_score = float(row["final_score"]),
            )
            for row in chunk_rows
        ],
        graph_context = [
            GraphNode(
                node_id        = str(row["node_id"]),
                canonical_name = row["canonical_name"],
                node_type      = row["node_type"],
                hop_distance   = row["hop_distance"],
                combined_score = float(row["combined_score"]),
            )
            for row in graph_rows
        ],
        turn_id      = str(turn_id),
        cache_status = cache_status,
    )


@router.get("/tts")
async def get_tts_stream(text: str):
    """
    Synthesize text-to-speech using the local Chatterbox service (port 5002)
    and stream back the synthesized WAV audio chunks.
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    chatterbox_url = "http://127.0.0.1:5002/v1/audio/speech"
    payload = {
        "model": "tts-1",
        "input": text,
        "voice": "andrew_ng_ref"
    }

    async def audio_stream_generator():
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                async with client.stream("POST", chatterbox_url, json=payload) as response:
                    if response.status_code != 200:
                        error_detail = await response.aread()
                        logger.error("Chatterbox API error: status %d, detail: %s", response.status_code, error_detail)
                        raise HTTPException(status_code=502, detail=f"Chatterbox TTS failed: status {response.status_code}")
                    async for chunk in response.iter_bytes():
                        yield chunk
            except httpx.RequestError as exc:
                logger.error("Failed to connect to Chatterbox server at %s: %s", chatterbox_url, exc)
                raise HTTPException(status_code=502, detail="Chatterbox server is unavailable or timed out")

    return StreamingResponse(audio_stream_generator(), media_type="audio/wav")


class TripletRow(BaseModel):
    node_id:         str
    canonical_name:  str
    node_type:       str
    metadata:        dict = Field(default_factory=dict)
    hop_distance:    int
    path_weight:     float
    vector_score:    float
    combined_score:  float
    predicates_path: list[str] = Field(default_factory=list)

class EdgeRow(BaseModel):
    id:            str
    subject_id:    str
    predicate:     str
    object_id:     str
    weight:        float
    evidence:      str

class GraphPayload(BaseModel):
    nodes: list[TripletRow]
    edges: list[EdgeRow]


# ── Graph data endpoint (for React Flow visualization) ────────────────────────
@router.get("/graph/{session_id}", response_model=GraphPayload)
async def get_session_graph(
    session_id: str,
    view:       str = "session",   # "session" or "global"
    db:         asyncpg.Pool = Depends(get_db),
    keys:       dict         = Depends(get_api_keys),
) -> GraphPayload:
    """
    Return the session or global knowledge graph (nodes + edges).
    Used by the React Flow visualizer component.
    """
    tenant_id = keys["tenant_id"]
    session_uuid = uuid.UUID(session_id)

    async with db.acquire() as conn:
        if view == "global":
            edge_rows = await conn.fetch(
                """
                SELECT id, subject_id, predicate, object_id, weight, coalesce(evidence, '') as evidence
                FROM relation_edges
                WHERE tenant_id = $1::uuid
                ORDER BY weight DESC
                LIMIT 150
                """,
                uuid.UUID(tenant_id),
            )
        else:
            edge_rows = await conn.fetch(
                """
                SELECT id, subject_id, predicate, object_id, weight, coalesce(evidence, '') as evidence
                FROM relation_edges
                WHERE tenant_id = $1::uuid AND session_id = $2::uuid
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
                evidence   = row["evidence"]
            )
        )

    return GraphPayload(nodes=nodes, edges=edges)


@router.post("/clear")
async def clear_tenant_memory(
    db:   asyncpg.Pool = Depends(get_db),
    keys: dict         = Depends(get_api_keys),
) -> dict[str, str]:
    """
    Delete all database records (turns, entity nodes, relation edges)
    associated with the tenant_id in the headers.
    Because of ON DELETE CASCADE, deleting the tenant from the tenants
    table automatically cleans up all associated records.
    """
    tenant_id = keys["tenant_id"]
    async with db.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM tenants WHERE id = $1::uuid",
                uuid.UUID(tenant_id),
            )
    logger.info("Cleared all memory for tenant %s", tenant_id)
    return {"status": "ok", "message": "Tenant learning memory cleared successfully."}


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False
