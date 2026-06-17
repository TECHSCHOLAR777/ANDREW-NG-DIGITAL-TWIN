"""
services/triplet_extractor.py
─────────────────────────────────────────────────────────────────────────────
Asynchronous knowledge graph triplet extractor.

Runs on a FastAPI BackgroundTask so it never blocks the HTTP response.
Uses the Gemini API (google-generativeai) to extract (subject, predicate,
object) triples from each conversation turn, then upserts them into
Supabase via the entity-resolution SQL functions defined in migration 002.

Architecture:
  HTTP response returns immediately ─► BackgroundTask queues triplet job
  BackgroundTask calls Gemini ─────────► parses structured JSON
  Validates & resolves entities ───────► upserts via PostgreSQL functions
  Writes relation_edges ───────────────► graph is updated async

Dependencies:
  pip install google-generativeai asyncpg tenacity pydantic
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import google.generativeai as genai
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# VALID PREDICATES (closed-world assumption keeps the graph clean)
# ─────────────────────────────────────────────────────────────────────────────
VALID_PREDICATES: set[str] = {
    "struggles_with",
    "mastered",
    "curious_about",
    "works_in",
    "studied",
    "applied",
    "confused_about",
    "wants_to_learn",
    "has_prerequisite",
    "related_to",
    "used_in",
    "named",
    "is",
}

VALID_NODE_TYPES: set[str] = {
    "Student", "Concept", "Project", "Tool", "Paper"
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RawTriplet:
    """A single SPO triple before entity resolution."""
    subject:        str
    subject_type:   str
    predicate:      str
    object:         str
    object_type:    str
    canonical_subj: str   # LLM-resolved canonical name
    canonical_obj:  str
    evidence:       str   # snippet from conversation supporting this triple
    confidence:     float = field(default=1.0)


@dataclass
class ResolvedTriplet:
    """SPO triple after DB entity resolution with UUIDs."""
    subject_id:  uuid.UUID
    predicate:   str
    object_id:   uuid.UUID
    weight:      float
    evidence:    str
    turn_id:     uuid.UUID


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI EXTRACTION PROMPT
# ─────────────────────────────────────────────────────────────────────────────
TRIPLET_EXTRACTION_SYSTEM_PROMPT = """
You are a knowledge-graph extraction engine. Your job is to extract structured
(subject, predicate, object) triples from a conversation turn between an AI
tutor (Andrew Ng) and a student.

RULES:
1. Only extract triples that involve the STUDENT's knowledge state—what they know, struggle with, are curious about, or are working on.
2. Subject is almost always the student or a concept.
3. Use ONLY these predicates and respect their directional mapping:
   - struggles_with: [Student] -[struggles_with]-> [Concept] (e.g. Student struggles with Backpropagation)
   - mastered: [Student] -[mastered]-> [Concept]
   - curious_about: [Student] -[curious_about]-> [Concept/Project/Tool/Paper]
   - works_in: [Student] -[works_in]-> [Concept/Project] (e.g. Student works in Retail Industry)
   - studied: [Student] -[studied]-> [Concept/Paper]
   - applied: [Student] -[applied]-> [Concept/Tool/Project] (e.g. Student applied Linear Regression)
   - confused_about: [Student] -[confused_about]-> [Concept]
   - wants_to_learn: [Student] -[wants_to_learn]-> [Concept]
   - has_prerequisite: [Concept] -[has_prerequisite]-> [Concept] (e.g. Deep Learning has_prerequisite Linear Algebra)
   - related_to: [Concept] -[related_to]-> [Concept]
   - used_in: [Concept/Tool] -[used_in]-> [Project/Concept] (e.g. Machine Learning -[used_in]-> Customer Support Routing. The subject is ALWAYS the tool or concept used, and the object is the application or project where it is used. Do NOT reverse this direction.)
   - named: [Student] -[named]-> [Name (raw_name of the student)]
   - is: [Student] -[is]-> [Role/Attribute] (e.g. Student -[is]-> Product Manager)
4. For each entity, provide:
   - raw_name: exactly as it appeared in conversation
   - canonical_name: the standard, canonical name (e.g. "NNs" → "Neural Networks")
   - type: one of [Student, Concept, Project, Tool, Paper]
5. Include a short evidence quote (< 30 words) from the conversation.
6. Estimate confidence 0.0–1.0 for each triple.
7. Return ONLY valid JSON, no markdown, no preamble.

OUTPUT FORMAT (strict JSON array):
[
  {
    "subject_raw":       "student",
    "subject_canonical": "Student",
    "subject_type":      "Student",
    "predicate":         "struggles_with",
    "object_raw":        "backprop",
    "object_canonical":  "Backpropagation",
    "object_type":       "Concept",
    "evidence":          "I keep getting confused during the chain rule step",
    "confidence":        0.9
  }
]
""".strip()


_local_embed_model = None

def _get_local_embed_model():
    global _local_embed_model
    if _local_embed_model is None:
        from sentence_transformers import SentenceTransformer
        _local_embed_model = SentenceTransformer("all-mpnet-base-v2")
    return _local_embed_model

async def _compute_embedding(text: str) -> list[float]:
    """Compute a 768-dim embedding locally using sentence-transformers."""
    loop = asyncio.get_event_loop()
    model = _get_local_embed_model()
    result = await loop.run_in_executor(
        None,
        lambda: model.encode(text).tolist()
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TRIPLET EXTRACTOR CLASS
# ─────────────────────────────────────────────────────────────────────────────
class TripletExtractor:
    """
    Extracts knowledge-graph triples from a conversation turn and persists
    them to Supabase.

    Usage (from FastAPI route):
        extractor = TripletExtractor(db_pool, gemini_api_key)
        background_tasks.add_task(
            extractor.process_turn,
            tenant_id=tenant_id,
            turn_id=turn.id,
            user_content=user_message,
            assistant_content=assistant_reply,
        )
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        gemini_api_key: str,
        gemini_model: str = "gemini-2.5-flash",  # flash = fast + cheap
    ):
        self.db = db_pool
        self.model_name = gemini_model
        genai.configure(api_key=gemini_api_key)
        self._model = genai.GenerativeModel(
            model_name=gemini_model,
            generation_config=genai.GenerationConfig(
                temperature=0.1,           # deterministic extraction
                max_output_tokens=8192,    # Gemini 2.5 Flash thinking tokens
                                           # count against this budget
            ),
            system_instruction=TRIPLET_EXTRACTION_SYSTEM_PROMPT,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC ENTRYPOINT (called as BackgroundTask)
    # ─────────────────────────────────────────────────────────────────────────
    async def process_turn(
        self,
        tenant_id: uuid.UUID,
        turn_id: uuid.UUID,
        user_content: str,
        assistant_content: str,
        session_id: uuid.UUID,
        student_canonical: str = "Student",
    ) -> None:
        """
        Main async pipeline:
          1. Call Gemini to extract raw triplets from the conversation turn.
          2. Validate predicates and node types.
          3. Upsert entities into entity_nodes via resolve/upsert SQL fns.
          4. Upsert relation_edges into the graph.
          5. Mark the conversation_turn as processed.
        """
        logger.info("TripletExtractor: processing turn %s for tenant %s (session %s)", turn_id, tenant_id, session_id)

        try:
            # Step 1: Extract triplets from Gemini
            raw_triplets = await self._extract_from_gemini(
                user_content, assistant_content
            )

            if not raw_triplets:
                logger.info("No triplets extracted for turn %s", turn_id)
                await self._mark_turn_processed(turn_id)
                return

            # Step 2: Validate
            valid_triplets = self._validate_triplets(raw_triplets)

            # Step 3 & 4: Upsert to DB in a single transaction
            resolved = await self._resolve_and_upsert(
                tenant_id, turn_id, session_id, valid_triplets, student_canonical
            )

            logger.info(
                "TripletExtractor: inserted %d edges for turn %s",
                len(resolved), turn_id
            )

        except Exception as exc:
            # Never crash the background task; log for observability
            logger.exception("TripletExtractor failed for turn %s: %s", turn_id, exc)
        finally:
            await self._mark_turn_processed(turn_id)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: GEMINI EXTRACTION
    # ─────────────────────────────────────────────────────────────────────────
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _extract_from_gemini(
        self,
        user_content: str,
        assistant_content: str,
    ) -> list[RawTriplet]:
        """Call Gemini API and parse the returned JSON triplets."""

        conversation_text = (
            f"STUDENT: {user_content}\n\n"
            f"ANDREW NG: {assistant_content}"
        )

        # Run in thread pool — google-generativeai is sync
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._model.generate_content(conversation_text),
        )

        raw_text = response.text.strip()

        # Strip any accidental markdown fences
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        try:
            data: list[dict[str, Any]] = json.loads(raw_text)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failure: %s\nRaw: %s", e, raw_text[:500])
            return []

        triplets: list[RawTriplet] = []
        for item in data:
            try:
                triplets.append(RawTriplet(
                    subject        = item["subject_raw"],
                    subject_type   = item.get("subject_type", "Concept"),
                    predicate      = item["predicate"],
                    object         = item["object_raw"],
                    object_type    = item.get("object_type", "Concept"),
                    canonical_subj = item["subject_canonical"],
                    canonical_obj  = item["object_canonical"],
                    evidence       = item.get("evidence", ""),
                    confidence     = float(item.get("confidence", 1.0)),
                ))
            except (KeyError, ValueError) as e:
                logger.debug("Skipping malformed triplet item: %s — %s", item, e)

        return triplets

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2: VALIDATION
    # ─────────────────────────────────────────────────────────────────────────
    def _validate_triplets(self, triplets: list[RawTriplet]) -> list[RawTriplet]:
        """Filter triplets with invalid predicates and normalize node types."""
        valid = []
        for t in triplets:
            if t.predicate not in VALID_PREDICATES:
                logger.debug("Rejecting invalid predicate '%s'", t.predicate)
                continue
            # Normalize non-standard node types to "Concept" instead of
            # dropping the whole triplet. The LLM sometimes returns types
            # like "Role", "Attribute", "Industry" which are semantically
            # fine but not in our closed-world set.
            if t.subject_type not in VALID_NODE_TYPES:
                logger.debug("Normalizing subject_type '%s' → 'Concept'", t.subject_type)
                t.subject_type = "Concept"
            if t.object_type not in VALID_NODE_TYPES:
                logger.debug("Normalizing object_type '%s' → 'Concept'", t.object_type)
                t.object_type = "Concept"
            if t.confidence < 0.5:
                logger.debug("Skipping low-confidence triplet (%.2f)", t.confidence)
                continue
            valid.append(t)
        return valid

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3 & 4: ENTITY RESOLUTION + EDGE UPSERT
    # ─────────────────────────────────────────────────────────────────────────
    async def _resolve_and_upsert(
        self,
        tenant_id: uuid.UUID,
        turn_id: uuid.UUID,
        session_id: uuid.UUID,
        triplets: list[RawTriplet],
        student_canonical: str,
    ) -> list[ResolvedTriplet]:
        """
        For each triplet:
          1. Collect all unique canonical names and retrieve or compute their embeddings upfront.
          2. Open transaction and upsert subject and object via upsert_entity() SQL function.
          3. Fast-update embeddings from pre-computed values without awaiting CPU/network logic.
          4. Insert or merge the relation_edge (by weight accumulation).
        """
        resolved: list[ResolvedTriplet] = []

        # Collect unique canonical names
        unique_canonical_names = set()
        for t in triplets:
            if t.canonical_subj:
                unique_canonical_names.add(t.canonical_subj)
            if t.canonical_obj:
                unique_canonical_names.add(t.canonical_obj)

        existing_embeddings = {}
        if unique_canonical_names:
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT canonical_name, embedding
                    FROM entity_nodes
                    WHERE tenant_id = $1 AND canonical_name = ANY($2::text[]) AND embedding IS NOT NULL
                    """,
                    tenant_id,
                    list(unique_canonical_names)
                )
                for r in rows:
                    existing_embeddings[r["canonical_name"]] = r["embedding"]

        # Compute embeddings upfront for any missing ones
        missing_names = [name for name in unique_canonical_names if name and name.strip() and name not in existing_embeddings]
        if missing_names:
            logger.info("Computing embeddings upfront for %d missing entities", len(missing_names))
            embeddings_list = await asyncio.gather(*[_compute_embedding(name) for name in missing_names])
            for name, emb in zip(missing_names, embeddings_list):
                existing_embeddings[name] = emb

        async with self.db.acquire() as conn:
            async with conn.transaction():
                for t in triplets:
                    # ── Upsert SUBJECT ──────────────────────────────────────
                    subj_id: uuid.UUID = await conn.fetchval(
                        """
                        SELECT upsert_entity($1, $2, $3, $4, $5::jsonb)
                        """,
                        tenant_id,
                        t.canonical_subj,      # canonical name
                        t.subject_type,
                        t.subject,             # raw alias
                        json.dumps({}),
                    )

                    # ── Upsert OBJECT ───────────────────────────────────────
                    obj_id: uuid.UUID = await conn.fetchval(
                        """
                        SELECT upsert_entity($1, $2, $3, $4, $5::jsonb)
                        """,
                        tenant_id,
                        t.canonical_obj,
                        t.object_type,
                        t.object,             # raw alias
                        json.dumps({}),
                    )

                    if subj_id is None or obj_id is None:
                        logger.warning("Failed to resolve entities for triplet: %s", t)
                        continue

                    # ── Update node embeddings if missing (fast database update) ──
                    subj_missing = await conn.fetchval(
                        "SELECT id FROM entity_nodes WHERE id = $1 AND embedding IS NULL",
                        subj_id
                    )
                    if subj_missing and t.canonical_subj in existing_embeddings:
                        await conn.execute(
                            "UPDATE entity_nodes SET embedding = $1::vector WHERE id = $2",
                            existing_embeddings[t.canonical_subj],
                            subj_id
                        )

                    # Check if object embedding is missing
                    obj_missing = await conn.fetchval(
                        "SELECT id FROM entity_nodes WHERE id = $1 AND embedding IS NULL",
                        obj_id
                    )
                    if obj_missing and t.canonical_obj in existing_embeddings:
                        await conn.execute(
                            "UPDATE entity_nodes SET embedding = $1::vector WHERE id = $2",
                            existing_embeddings[t.canonical_obj],
                            obj_id
                        )

                    # ── Upsert RELATION EDGE ────────────────────────────────
                    # If this (subject, predicate, object) edge already exists in the session,
                    # accumulate weight (repeated observations strengthen edge).
                    await conn.execute(
                        """
                        INSERT INTO relation_edges
                            (tenant_id, session_id, subject_id, predicate, object_id,
                             weight, source_turn_id, evidence)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT (tenant_id, session_id, subject_id, predicate, object_id)
                        DO UPDATE SET
                            weight         = LEAST(
                                relation_edges.weight + EXCLUDED.weight * 0.1,
                                2.0               -- cap weight at 2.0
                            ),
                            source_turn_id = EXCLUDED.source_turn_id,
                            evidence       = EXCLUDED.evidence,
                            updated_at     = NOW()
                        """,
                        tenant_id,
                        session_id,
                        subj_id,
                        t.predicate,
                        obj_id,
                        t.confidence,   # initial weight = confidence
                        turn_id,
                        t.evidence,
                    )

                    resolved.append(ResolvedTriplet(
                        subject_id = subj_id,
                        predicate  = t.predicate,
                        object_id  = obj_id,
                        weight     = t.confidence,
                        evidence   = t.evidence,
                        turn_id    = turn_id,
                    ))

        return resolved

    # ─────────────────────────────────────────────────────────────────────────
    # UTILITY
    # ─────────────────────────────────────────────────────────────────────────
    async def _mark_turn_processed(self, turn_id: uuid.UUID) -> None:
        """Mark the conversation_turn row so we don't re-process it."""
        async with self.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE conversation_turns
                SET    triplets_extracted = TRUE
                WHERE  id = $1
                """,
                turn_id,
            )
