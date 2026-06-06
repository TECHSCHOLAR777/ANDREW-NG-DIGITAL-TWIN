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
import os
import httpx
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


HF_TOKEN = os.getenv("HF_TOKEN")
HF_MODEL_ID = "sentence-transformers/all-mpnet-base-v2"
HF_API_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL_ID}"

async def _compute_embedding(text: str, gemini_key: str) -> list[float]:
    """Compute a 768-dim embedding using Hugging Face Serverless Inference API."""
    headers = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}
    payload = {"inputs": text}
    
    # Try up to 5 times (helps when Hugging Face is loading/warming up the model on demand)
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(HF_API_URL, headers=headers, json=payload)
                if response.status_code == 200:
                    val = response.json()
                    # HF can return nested lists or flat list of floats
                    if isinstance(val, list):
                        if len(val) > 0 and isinstance(val[0], list):
                            return [float(x) for x in val[0]]
                        return [float(x) for x in val]
                elif response.status_code == 503:
                    # Model loading, wait and retry
                    logger.warning("Hugging Face model is loading/warming up. Retrying in 5s (attempt %d/5)...", attempt+1)
                    await asyncio.sleep(5)
                    continue
                else:
                    logger.error("Hugging Face Inference API error %d: %s", response.status_code, response.text)
        except Exception as e:
            logger.error("Error connecting to Hugging Face Inference API: %s", e)
            if attempt == 4:
                raise
        await asyncio.sleep(2)
        
    raise Exception("Failed to retrieve embeddings from Hugging Face Serverless Inference API after multiple attempts.")


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
    """Call the vector_anchored_subgraph SQL function."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM vector_anchored_subgraph(
                $1::uuid,    -- tenant_id
                $2::vector,  -- query_embedding
                5,           -- top_k anchor nodes
                0.5          -- cosine threshold
            )
            """,
            uuid.UUID(tenant_id),
            embedding,
        )
    return rows


def _build_graph_context_summary(graph_nodes: list[asyncpg.Record]) -> str:
    """
    Convert graph traversal results into a concise text summary
    injected into the dynamic (non-cached) part of the prompt.
    """
    if not graph_nodes:
        return "No prior knowledge graph data available for this student."

    lines = ["STUDENT LEARNING GRAPH:"]
    struggling = [n for n in graph_nodes if "struggles_with" in str(n.get("predicates_path", []))]
    mastered   = [n for n in graph_nodes if "mastered"       in str(n.get("predicates_path", []))]
    curious    = [n for n in graph_nodes if "curious_about"  in str(n.get("predicates_path", []))]

    if struggling:
        lines.append("  Struggling with: " + ", ".join(
            n["canonical_name"] for n in struggling[:3]
        ))
    if mastered:
        lines.append("  Has mastered: " + ", ".join(
            n["canonical_name"] for n in mastered[:3]
        ))
    if curious:
        lines.append("  Curious about: " + ", ".join(
            n["canonical_name"] for n in curious[:3]
        ))

    # Include all nodes for completeness
    all_concepts = [n["canonical_name"] for n in graph_nodes[:10]]
    lines.append("  Related concepts: " + ", ".join(all_concepts))
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

    # ── Step 2: Parallel retrieval ─────────────────────────────────────────
    chunk_rows, graph_rows = await asyncio.gather(
        _run_hybrid_retrieval(db, tenant_id, embedding, body.message, body.top_k_chunks),
        _run_graph_traversal(db, tenant_id, embedding),
    )

    chunk_texts = [row["chunk_text"] for row in chunk_rows]
    graph_summary = _build_graph_context_summary(graph_rows)

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
    db:         asyncpg.Pool = Depends(get_db),
    keys:       dict         = Depends(get_api_keys),
) -> GraphPayload:
    """
    Return the full knowledge graph (nodes + edges) for a session/tenant.
    Used by the React Flow visualizer component.
    """
    tenant_id = keys["tenant_id"]

    async with db.acquire() as conn:
        node_rows = await conn.fetch(
            """
            SELECT id, canonical_name, node_type, metadata
            FROM entity_nodes
            WHERE tenant_id = $1::uuid
            """,
            uuid.UUID(tenant_id),
        )
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

    nodes = []
    for row in node_rows:
        node_type = row["node_type"]
        hop = 0 if node_type == "Student" else 1
        score = 1.0 if node_type == "Student" else 0.6
        nodes.append(
            TripletRow(
                node_id        = str(row["id"]),
                canonical_name = row["canonical_name"],
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
