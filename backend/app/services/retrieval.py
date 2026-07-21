"""
services/retrieval.py
─────────────────────────────────────────────────────────────────────────────
Owns the whole retrieval path so the chat router stays orchestration only.

Pipeline for one turn:

    user message
      └─ maybe_rewrite_query()      resolve follow-ups into standalone questions
          └─ compute_embedding()    local mpnet, dedicated thread pool
              └─ hybrid_retrieve()  pgvector + FTS fused with RRF (SQL)
                  └─ expand_neighbors()  pull chunk_index ±N from same file
                      └─ merge into contiguous passages
                          └─ score_confidence()  decide if we are grounded
                              └─ build_knowledge_block()  prompt-ready text

Design notes
────────────
* Chunks are assembled FRESH every turn. They are never cached across turns —
  a session that moves from gradient descent to transformers must not keep
  reading gradient descent chunks.
* Neighbour expansion exists because chunks are ~1000 chars with no overlap.
  A retrieved chunk often uses notation the previous chunk defined; handing
  the model an isolated fragment invites it to fill gaps from parametric
  memory, which is exactly what grounding is supposed to prevent.
* Confidence scoring lets the tutor say "this is outside my notes" instead of
  silently presenting ten irrelevant chunks as authoritative.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import asyncpg

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# TUNABLES (env-overridable so they can be swept without editing code)
# ─────────────────────────────────────────────────────────────────────────────
EMBED_MODEL_NAME     = os.getenv("EMBED_MODEL", "all-mpnet-base-v2")
EMBED_WORKERS        = int(os.getenv("EMBED_WORKERS", "2"))
NEIGHBOR_WINDOW      = int(os.getenv("RETRIEVAL_NEIGHBOR_WINDOW", "1"))
RRF_K                = int(os.getenv("RETRIEVAL_RRF_K", "60"))
VECTOR_WEIGHT        = float(os.getenv("RETRIEVAL_VECTOR_WEIGHT", "0.65"))
FTS_WEIGHT           = float(os.getenv("RETRIEVAL_FTS_WEIGHT", "0.35"))
MIN_COSINE_GROUNDED  = float(os.getenv("RETRIEVAL_MIN_COSINE", "0.35"))
ENABLE_QUERY_REWRITE = os.getenv("ENABLE_QUERY_REWRITE", "true").lower() != "false"
REWRITE_MODEL        = os.getenv("REWRITE_MODEL", "gemini-2.5-flash")


# ─────────────────────────────────────────────────────────────────────────────
# EMBEDDING
# Runs on a dedicated bounded thread pool. Previously this used the default
# asyncio executor, which is shared with the blocking Gemini SDK calls — a
# CPU-bound encode and a network-bound generation competing for the same few
# threads meant each could starve the other under load.
# ─────────────────────────────────────────────────────────────────────────────
_embed_model = None
_embed_pool: ThreadPoolExecutor | None = None


def _get_embed_pool() -> ThreadPoolExecutor:
    global _embed_pool
    if _embed_pool is None:
        _embed_pool = ThreadPoolExecutor(
            max_workers=EMBED_WORKERS,
            thread_name_prefix="embed",
        )
    return _embed_pool


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model %s ...", EMBED_MODEL_NAME)
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
        logger.info("Embedding model ready.")
    return _embed_model


def preload_embed_model() -> None:
    """Warm the model at startup so the first request does not pay for it."""
    get_embed_model()


async def compute_embedding(text: str) -> list[float]:
    """Compute a 768-dim embedding locally (no API key involved)."""
    loop = asyncio.get_running_loop()
    model = get_embed_model()
    return await loop.run_in_executor(
        _get_embed_pool(),
        lambda: model.encode(text, normalize_embeddings=False).tolist(),
    )


def shutdown_embed_pool() -> None:
    global _embed_pool
    if _embed_pool is not None:
        _embed_pool.shutdown(wait=False)
        _embed_pool = None


# ─────────────────────────────────────────────────────────────────────────────
# QUERY REWRITING
# ─────────────────────────────────────────────────────────────────────────────
# Words that typically open a dependent follow-up ("why?", "and the second
# one?", "go deeper"). A message starting with one of these and carrying no
# new subject almost certainly refers back to the previous turn.
_FOLLOWUP_OPENERS = {
    "why", "how", "and", "but", "so", "ok", "okay", "yes", "no", "really",
    "more", "again", "continue", "go", "also", "then", "what", "which",
    "explain", "elaborate", "expand", "tell", "show", "give",
}

_BACKREF = re.compile(
    r"\b(it|its|that|this|those|these|them|they|there|the former|the latter|"
    r"the first|the second|the third|above|previous|last one)\b",
    re.IGNORECASE,
)

_REWRITE_PROMPT = (
    "Rewrite the student's latest message into a single standalone question "
    "that can be understood with no conversation history, so it can be used "
    "for document search.\n"
    "Rules:\n"
    "- Resolve pronouns and references using the conversation.\n"
    "- Keep the student's technical vocabulary.\n"
    "- If the message is already standalone, return it unchanged.\n"
    "- Return ONLY the rewritten question, no preamble, no quotes.\n"
)


def needs_rewrite(message: str, turn_history: list[dict]) -> bool:
    """
    Cheap heuristic gate. Rewriting every query would add latency and cost for
    no benefit on well-formed questions, so only fire when the message looks
    dependent on prior context.
    """
    if not turn_history:
        return False

    words = re.findall(r"[A-Za-z']+", message)
    if not words:
        return False

    lowered = [w.lower() for w in words]

    # Very short messages are almost always follow-ups ("why?", "go on")
    if len(words) <= 4:
        return True
    # A back-reference ("that step", "why does it fail") needs prior context
    # to resolve. This is the strongest signal and covers most real follow-ups.
    if len(words) <= 18 and _BACKREF.search(message):
        return True
    # Opening word alone is a weak signal: "what", "how" and "why" begin plenty
    # of fully standalone questions ("What is the bias-variance tradeoff in
    # linear regression?"). Only treat it as dependent when the message is also
    # too short to carry its own subject.
    if lowered[0] in _FOLLOWUP_OPENERS and len(words) <= 6:
        return True
    return False


async def maybe_rewrite_query(
    message: str,
    turn_history: list[dict],
    gemini_key: str,
) -> tuple[str, bool]:
    """
    Returns (query_for_retrieval, was_rewritten).

    Failure is non-fatal: if the rewrite call errors or times out we fall back
    to the raw message. A degraded query beats a failed request.
    """
    if not ENABLE_QUERY_REWRITE or not needs_rewrite(message, turn_history):
        return message, False

    recent = turn_history[-4:]
    convo = "\n".join(
        f"{'Student' if t.get('role') == 'user' else 'Andrew'}: {t.get('content', '')[:600]}"
        for t in recent
    )

    # Routed through gemini_client so the API key stays scoped to this call.
    # Calling genai.configure() directly here would reintroduce the
    # cross-request key leak that module-global configuration causes.
    from . import gemini_client

    def _call() -> str:
        result = gemini_client.generate_sync(
            api_key            = gemini_key,
            model              = REWRITE_MODEL,
            contents           = [{
                "role": "user",
                "parts": [{"text": (
                    f"CONVERSATION SO FAR:\n{convo}\n\n"
                    f"LATEST MESSAGE:\n{message}\n\nStandalone question:"
                )}],
            }],
            system_instruction = _REWRITE_PROMPT,
            temperature        = 0.0,
            max_output_tokens  = 512,
            thinking_budget    = 0,   # rewriting needs no internal reasoning
        )
        return result.text.strip()

    try:
        rewritten = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(None, _call),
            timeout=8.0,
        )
    except Exception as exc:  # noqa: BLE001 - degradation is intentional
        logger.warning("Query rewrite failed, using raw message: %s", exc)
        return message, False

    # Guard against a model that returns junk or an empty string
    if not rewritten or len(rewritten) > 600:
        return message, False

    if rewritten.strip().lower() == message.strip().lower():
        return message, False

    logger.info("Rewrote query: %r -> %r", message[:80], rewritten[:80])
    return rewritten, True


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Passage:
    """A contiguous run of chunks from one source file, ready for the prompt."""
    source_file:  str
    source_type:  str
    start_index:  int
    end_index:    int
    text:         str
    hit_ids:      list[str] = field(default_factory=list)  # chunks that actually ranked
    top_score:    float = 0.0
    # Set when this passage was pulled in to cover a prerequisite the student
    # is shaky on, rather than because it matched the question.
    prerequisite_for: str | None = None


@dataclass
class RetrievalResult:
    passages:        list[Passage]
    ranked_rows:     list[asyncpg.Record]   # original ranked hits, for citations
    confidence:      float                  # best cosine similarity seen
    is_grounded:     bool
    query_used:      str
    was_rewritten:   bool
    prerequisite_passages: list[Passage] = field(default_factory=list)
    prerequisites_used:    list[str] = field(default_factory=list)

    @property
    def chunk_texts(self) -> list[str]:
        return [p.text for p in self.passages]


# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVAL
# ─────────────────────────────────────────────────────────────────────────────
async def hybrid_retrieve(
    db: asyncpg.Pool,
    caller_tenant_id: str | None,
    embedding: list[float],
    query_text: str,
    top_k: int,
) -> list[asyncpg.Record]:
    """
    Fused pgvector + FTS retrieval via the hybrid_chunk_retrieval SQL function.

    caller_tenant_id is the USER, not the corpus owner. Since migration 011 a
    chunk is visible when it is shared corpus material or privately owned by
    the caller. Previously NULL meant "no tenant filter at all", which was safe
    only because one tenant owned every chunk; the first private upload would
    have leaked one user's documents to another.
    """
    corpus_uuid = uuid.UUID(caller_tenant_id) if caller_tenant_id else None
    async with db.acquire() as conn:
        return await conn.fetch(
            """
            SELECT * FROM hybrid_chunk_retrieval(
                $1::uuid, $2::vector, $3, $4, $5, $6, $7
            )
            """,
            corpus_uuid,
            embedding,
            query_text,
            top_k,
            RRF_K,
            VECTOR_WEIGHT,
            FTS_WEIGHT,
        )


async def expand_neighbors(
    db: asyncpg.Pool,
    caller_tenant_id: str | None,
    ranked_rows: list[asyncpg.Record],
    window: int = NEIGHBOR_WINDOW,
) -> list[asyncpg.Record]:
    """
    Fetch each hit plus its chunk_index neighbours from the same source file.

    Chunks were ingested with no overlap, so a hit frequently starts
    mid-explanation. Pulling the immediate neighbours restores the sentences
    that define the notation the hit relies on.
    """
    if not ranked_rows or window <= 0:
        return list(ranked_rows)

    corpus_uuid = uuid.UUID(caller_tenant_id) if caller_tenant_id else None
    chunk_ids = [uuid.UUID(str(r["chunk_id"])) for r in ranked_rows]

    async with db.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM fetch_chunk_neighbors($1::uuid, $2::uuid[], $3)",
            corpus_uuid,
            chunk_ids,
            window,
        )


def merge_into_passages(
    ranked_rows: list[asyncpg.Record],
    neighbor_rows: list[asyncpg.Record],
) -> list[Passage]:
    """
    Collapse chunks into contiguous passages per source file.

    Two hits that are one apart (indexes 12 and 14) become a single passage
    12-14 rather than two overlapping windows containing chunk 13 twice.
    Passages are ordered by the best score of any hit inside them.
    """
    hit_ids = {str(r["chunk_id"]) for r in ranked_rows}
    score_by_id = {str(r["chunk_id"]): float(r["final_score"]) for r in ranked_rows}

    by_file: dict[str, list[asyncpg.Record]] = {}
    for row in neighbor_rows:
        by_file.setdefault(row["source_file"], []).append(row)

    passages: list[Passage] = []
    for source_file, rows in by_file.items():
        rows.sort(key=lambda r: r["chunk_index"])

        run: list[asyncpg.Record] = []
        for row in rows:
            if run and row["chunk_index"] != run[-1]["chunk_index"] + 1:
                passages.append(_build_passage(source_file, run, hit_ids, score_by_id))
                run = []
            run.append(row)
        if run:
            passages.append(_build_passage(source_file, run, hit_ids, score_by_id))

    # Drop passages that contain no actual hit (can happen if a neighbour row
    # belongs to a run whose hit was deduplicated away)
    passages = [p for p in passages if p.hit_ids]
    passages.sort(key=lambda p: p.top_score, reverse=True)
    return passages


def _build_passage(
    source_file: str,
    run: list[asyncpg.Record],
    hit_ids: set[str],
    score_by_id: dict[str, float],
) -> Passage:
    ids_in_run = [str(r["chunk_id"]) for r in run]
    hits = [cid for cid in ids_in_run if cid in hit_ids]
    return Passage(
        source_file = source_file,
        source_type = run[0]["source_type"],
        start_index = run[0]["chunk_index"],
        end_index   = run[-1]["chunk_index"],
        text        = "\n\n".join(r["chunk_text"] for r in run),
        hit_ids     = hits,
        top_score   = max((score_by_id.get(c, 0.0) for c in hits), default=0.0),
    )


def score_confidence(ranked_rows: list[asyncpg.Record]) -> tuple[float, bool]:
    """
    Decide whether the corpus actually covers this question.

    RRF always returns its top-k, so a query about something Andrew never
    wrote about still comes back with ten chunks. Raw cosine similarity of the
    best vector hit is a cheap, honest proxy for coverage: fused RRF scores
    are rank-derived and say nothing about absolute relevance.
    """
    if not ranked_rows:
        return 0.0, False
    best = max(float(r["vector_score"] or 0.0) for r in ranked_rows)
    return best, best >= MIN_COSINE_GROUNDED


async def retrieve_context(
    db: asyncpg.Pool,
    caller_tenant_id: str | None,
    message: str,
    turn_history: list[dict],
    gemini_key: str,
    top_k: int,
    precomputed_embedding: list[float] | None = None,
    prerequisite_hints: list[str] | None = None,
) -> tuple[RetrievalResult, list[float]]:
    """
    Full retrieval path. Returns the result plus the embedding, which the
    caller reuses for graph traversal instead of encoding the same text twice.

    `prerequisite_hints` is what makes retrieval pedagogical rather than purely
    semantic. When the curriculum graph knows the question depends on a concept
    the student is not solid on, that concept is searched for as well, even
    though the student never mentioned it. A tutor asked about backpropagation
    by someone shaky on the chain rule fetches chain rule material; a plain
    retriever cannot, because the query does not contain those words.
    """
    query_text, was_rewritten = await maybe_rewrite_query(message, turn_history, gemini_key)

    if precomputed_embedding and len(precomputed_embedding) == 768 and not was_rewritten:
        embedding = precomputed_embedding
    else:
        embedding = await compute_embedding(query_text)

    ranked = await hybrid_retrieve(db, caller_tenant_id, embedding, query_text, top_k)
    confidence, is_grounded = score_confidence(ranked)

    # Grounding is judged on the question the student actually asked, before
    # any prerequisite material is folded in. Otherwise a strong hit on a
    # prerequisite could mask the fact that the question itself is uncovered.
    prerequisite_passages: list[Passage] = []
    if prerequisite_hints:
        prerequisite_passages = await _retrieve_prerequisites(
            db, caller_tenant_id, prerequisite_hints,
        )

    neighbors = await expand_neighbors(db, caller_tenant_id, ranked)
    passages = merge_into_passages(ranked, neighbors)

    logger.info(
        "Retrieval: %d hits -> %d passages | cosine=%.3f grounded=%s rewritten=%s prereq=%d",
        len(ranked), len(passages), confidence, is_grounded, was_rewritten,
        len(prerequisite_passages),
    )

    return (
        RetrievalResult(
            passages              = passages,
            ranked_rows           = list(ranked),
            confidence            = confidence,
            is_grounded           = is_grounded,
            query_used            = query_text,
            was_rewritten         = was_rewritten,
            prerequisite_passages = prerequisite_passages,
            prerequisites_used    = list(prerequisite_hints or []),
        ),
        embedding,
    )


async def _retrieve_prerequisites(
    db: asyncpg.Pool,
    caller_tenant_id: str | None,
    concepts: list[str],
    per_concept: int = 2,
) -> list[Passage]:
    """
    Fetch a small amount of material for each prerequisite concept.

    Deliberately shallow: two passages per concept, at most three concepts.
    The point is to give the tutor enough to bridge a gap in passing, not to
    turn every answer into a remedial lecture on things the student did not
    ask about.
    """
    out: list[Passage] = []
    for concept in concepts[:3]:
        try:
            embedding = await compute_embedding(concept)
            rows = await hybrid_retrieve(db, caller_tenant_id, embedding, concept, per_concept)
            if not rows:
                continue
            neighbors = await expand_neighbors(db, caller_tenant_id, rows, window=0)
            for passage in merge_into_passages(rows, neighbors or rows)[:per_concept]:
                passage.prerequisite_for = concept
                out.append(passage)
        except Exception as exc:  # noqa: BLE001 - never fail a turn over this
            logger.warning("Prerequisite retrieval failed for %r: %s", concept, exc)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BLOCK
# ─────────────────────────────────────────────────────────────────────────────
def build_knowledge_block(result: RetrievalResult) -> str:
    """
    Render retrieved passages for the prompt.

    When retrieval is weak the block says so explicitly rather than presenting
    marginal passages under a confident heading. The persona already knows to
    speak from general expertise and flag it; this gives it the signal it
    needs to actually do that, which it cannot infer when strong and weak
    retrieval look identical in the prompt.
    """
    if not result.passages:
        return (
            "KNOWLEDGE BASE: no relevant material was found in Andrew's "
            "writings or lectures for this question. Answer from general "
            "expertise and make it clear this is your own perspective rather "
            "than something you have written about.\n"
        )

    header = "KNOWLEDGE BASE (from Andrew's own lectures, books and newsletters):\n"
    if not result.is_grounded:
        header = (
            "KNOWLEDGE BASE (WEAK MATCH): the passages below are the closest "
            "material available but may not directly address the question. "
            "Rely on them only where they genuinely apply, and otherwise "
            "answer from general expertise and say so.\n"
        )

    parts = [header]

    # Prerequisite material is labelled separately and explicitly, so the model
    # knows it is background the student did not ask for. Without the label it
    # reads as part of the answer and the tutor lectures on the wrong topic.
    if result.prerequisite_passages:
        parts.append(
            "\nBACKGROUND THIS STUDENT MAY NEED: the curriculum shows this "
            "question depends on concepts they are not yet solid on. Weave a "
            "brief bridge in where it helps. Do not turn the answer into a "
            "lesson on these.\n"
        )
        for p in result.prerequisite_passages:
            label = (p.prerequisite_for or "background").title()
            parts.append(f"\n[Prerequisite: {label}]\n{p.text}\n")
        parts.append("\nMATERIAL FOR THE QUESTION ITSELF:\n")

    for i, p in enumerate(result.passages, start=1):
        span = (
            f"chunk {p.start_index}"
            if p.start_index == p.end_index
            else f"chunks {p.start_index}-{p.end_index}"
        )
        label = p.source_file.replace("_", " ").replace(".txt", "")
        parts.append(f"\n[Passage {i} | {label} | {span}]\n{p.text}\n")

    return "".join(parts)
