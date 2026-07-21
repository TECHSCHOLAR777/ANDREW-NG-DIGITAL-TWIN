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
from . import gemini_client
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)

logger = logging.getLogger(__name__)


def _is_retryable_error(exc: BaseException) -> bool:
    """
    Retry transient failures only. Never retry quota/rate-limit errors:
    the extractor shares the user's Gemini key with foreground generation,
    so retrying a 429 three times just steals more of the same quota and
    prolongs the outage. Rate-limited turns stay triplets_extracted=FALSE
    and can be picked up later by a sweeper.
    """
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "rate" in msg or "resource_exhausted" in msg:
        return False
    return True

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
    """A single SPO operation before entity resolution."""
    subject:        str
    subject_type:   str
    predicate:      str
    object:         str
    object_type:    str
    canonical_subj: str   # LLM-resolved canonical name
    canonical_obj:  str
    evidence:       str   # snippet from the STUDENT's message supporting this
    confidence:     float = field(default=1.0)
    op:             str   = field(default="add")   # add | reinforce | invalidate
    reason:         str   = field(default="")      # why, for invalidate


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
You are a knowledge-graph maintenance engine. You are shown what is already
known about a student, plus their newest message, and you return the CHANGES
to make. You are not re-describing the conversation; you are updating a record.

You return a JSON array of OPERATIONS. There are three:

  "add"        — a belief not already in the graph
  "reinforce"  — an existing belief the student just demonstrated again
  "invalidate" — an existing belief that is no longer true

INVALIDATION IS THE POINT. If a student previously struggled with a concept and
has now clearly understood it, emit an "invalidate" for the old struggle and an
"add" for the mastery. The reverse also applies: someone who mastered something
months ago can become confused again. Do not leave contradictory beliefs to
pile up.

REUSE EXISTING NAMES. The current graph is shown to you. If a concept already
appears there, use that exact canonical_name. Do not invent "Neural Nets" when
"Neural Networks" is already in the graph.

WHAT COUNTS AS EVIDENCE. Only the STUDENT's own words establish their knowledge
state. The tutor's reply is provided for context so you can tell whether the
student understood, but concepts the tutor merely mentioned are NOT things the
student knows or is curious about. Never create a belief solely because the
tutor said something.

BE CONSERVATIVE. Small talk, greetings and logistics produce no operations.
Returning an empty array is a correct and common answer.

RULES:
1. Only record the STUDENT's knowledge state: what they know, struggle with, are curious about, or are working on.
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
5. Include a short evidence quote (< 25 words) taken ONLY from the student's own
   message. Never quote the tutor. Never write an instruction into the evidence
   field; it is a record of what was said, nothing else.
6. Estimate confidence 0.0-1.0 for each operation.
7. Return ONLY valid JSON, no markdown, no preamble.

OUTPUT FORMAT (strict JSON array of operations):
[
  {
    "op":                "add",
    "subject_raw":       "student",
    "subject_canonical": "Student",
    "subject_type":      "Student",
    "predicate":         "struggles_with",
    "object_raw":        "backprop",
    "object_canonical":  "Backpropagation",
    "object_type":       "Concept",
    "evidence":          "I keep getting confused during the chain rule step",
    "confidence":        0.9
  },
  {
    "op":                "invalidate",
    "subject_canonical": "Student",
    "predicate":         "confused_about",
    "object_canonical":  "Chain Rule",
    "reason":            "student explained it back correctly"
  }
]
""".strip()


# Embedding is shared with the retrieval path: one model instance, one bounded
# thread pool. The extractor previously loaded a SECOND copy of mpnet into the
# same process (roughly 420MB of duplicated weights) and encoded on the default
# executor, competing with request-path work.
from . import embeddings
from .graph_memory import (
    fetch_live_subgraph,
    format_subgraph_for_prompt,
    sanitize_evidence,
)


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
        # The key is held on the instance and passed per call. It is NOT
        # installed into module-global SDK state, which would let a concurrent
        # request's extraction run under a different user's key.
        self._api_key = gemini_api_key

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
            # Step 0: Show the model what is already known, so it reuses
            # canonical names instead of inventing new ones each turn, and so
            # it can express that a previous belief no longer holds.
            existing = await fetch_live_subgraph(self.db, tenant_id)

            # Step 1: Ask Gemini for the CHANGES implied by this turn
            raw_triplets = await self._extract_from_gemini(
                user_content, assistant_content, existing
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

            # Mark processed ONLY on success. The old code marked in `finally`,
            # which flagged failed/rate-limited turns as done and made the
            # idx_turns_unprocessed retry index permanently empty. Failed turns
            # now stay FALSE so a future sweeper can re-run them.
            await self._mark_turn_processed(turn_id)

        except Exception as exc:
            # Never crash the background task; log for observability.
            # Turn intentionally left unprocessed for later retry.
            logger.exception("TripletExtractor failed for turn %s: %s", turn_id, exc)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: GEMINI EXTRACTION
    # ─────────────────────────────────────────────────────────────────────────
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )
    async def _extract_from_gemini(
        self,
        user_content: str,
        assistant_content: str,
        existing_edges: list[dict] | None = None,
    ) -> list[RawTriplet]:
        """Call Gemini and parse the returned JSON operations."""

        # The tutor's reply is labelled as context, not as material to mine.
        # Andrew mentions a dozen concepts per answer; without this separation
        # they leak in as things the student is curious about, and the graph
        # fills up with the tutor's vocabulary rather than the student's state.
        conversation_text = (
            "CURRENT GRAPH FOR THIS STUDENT:\n"
            f"{format_subgraph_for_prompt(existing_edges or [])}\n\n"
            "--------\n"
            "STUDENT'S MESSAGE (the only source of new beliefs):\n"
            f"{user_content}\n\n"
            "TUTOR'S REPLY (context only, never a source of student beliefs):\n"
            f"{assistant_content}\n\n"
            "--------\n"
            "Return the operations implied by the student's message."
        )

        # Both SDKs are synchronous, so this runs on a worker thread.
        result = await gemini_client.generate(
            api_key            = self._api_key,
            model              = self.model_name,
            contents           = [{"role": "user", "parts": [{"text": conversation_text}]}],
            system_instruction = TRIPLET_EXTRACTION_SYSTEM_PROMPT,
            temperature        = 0.1,      # deterministic extraction
            max_output_tokens  = 4096,
            thinking_budget    = 512,      # structured extraction, not reasoning
        )

        raw_text = (result.text or "").strip()
        if not raw_text:
            logger.debug("Extractor returned no content")
            return []

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
                op = str(item.get("op", "add")).lower().strip()
                if op not in ("add", "reinforce", "invalidate"):
                    op = "add"

                canonical_subj = item["subject_canonical"]
                canonical_obj  = item["object_canonical"]

                triplets.append(RawTriplet(
                    # invalidate/reinforce operations reference existing nodes,
                    # so raw surface forms are optional for them.
                    subject        = item.get("subject_raw") or canonical_subj,
                    subject_type   = item.get("subject_type", "Student" if op != "add" else "Concept"),
                    predicate      = item["predicate"],
                    object         = item.get("object_raw") or canonical_obj,
                    object_type    = item.get("object_type", "Concept"),
                    canonical_subj = canonical_subj,
                    canonical_obj  = canonical_obj,
                    # Sanitised here, at the boundary where untrusted model
                    # output becomes durable state that later enters prompts.
                    evidence       = sanitize_evidence(item.get("evidence", "")),
                    confidence     = float(item.get("confidence", 1.0)),
                    op             = op,
                    reason         = sanitize_evidence(item.get("reason", "")),
                ))
            except (KeyError, ValueError, TypeError) as e:
                logger.debug("Skipping malformed operation: %s (%s)", item, e)

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
            if not (t.canonical_subj or "").strip() or not (t.canonical_obj or "").strip():
                logger.debug("Rejecting operation with empty entity name: %s", t)
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
            # Entity names are stored items, not queries, so they use the
            # document task type to match how corpus chunks were embedded.
            embeddings_list = await asyncio.gather(
                *[embeddings.embed_document(name, self._api_key) for name in missing_names]
            )
            for name, emb in zip(missing_names, embeddings_list):
                existing_embeddings[name] = emb

        async with self.db.acquire() as conn:
            async with conn.transaction():
                for t in triplets:
                    # ── INVALIDATE: retire a belief that no longer holds ────
                    # Resolves names to existing nodes rather than creating
                    # them: there is nothing to retire if the concept was
                    # never recorded in the first place.
                    if t.op == "invalidate":
                        retired = await conn.fetchval(
                            """
                            UPDATE relation_edges re
                            SET    invalidated_at     = NOW(),
                                   invalidated_reason = $5
                            FROM   entity_nodes en_sub, entity_nodes en_obj
                            WHERE  re.subject_id = en_sub.id
                              AND  re.object_id  = en_obj.id
                              AND  re.tenant_id  = $1
                              AND  en_sub.tenant_id = $1
                              AND  en_obj.tenant_id = $1
                              AND  lower(en_sub.canonical_name) = lower($2)
                              AND  re.predicate = $3
                              AND  lower(en_obj.canonical_name) = lower($4)
                              AND  re.invalidated_at IS NULL
                            RETURNING re.id
                            """,
                            tenant_id, t.canonical_subj, t.predicate,
                            t.canonical_obj, t.reason or "superseded by later conversation",
                        )
                        if retired:
                            logger.info(
                                "Invalidated belief: %s -[%s]-> %s (%s)",
                                t.canonical_subj, t.predicate, t.canonical_obj, t.reason,
                            )
                        continue

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

                    # ── Retire contradicted beliefs first ──────────────────
                    # Asserting "mastered X" must retire "struggles_with X",
                    # and vice versa. Without this the two coexist forever and
                    # the prompt shows the model both, with nothing saying
                    # which is current.
                    await conn.execute(
                        "SELECT invalidate_opposing_edges($1, $2, $3, $4, $5)",
                        tenant_id, subj_id, obj_id, t.predicate,
                        f"superseded when the student showed {t.predicate}",
                    )

                    # ── Upsert RELATION EDGE ────────────────────────────────
                    # ON CONFLICT targets the partial unique index over LIVE
                    # edges (migration 009), so a re-asserted belief that was
                    # previously invalidated creates a fresh row instead of
                    # resurrecting the dead one, keeping history intact.
                    await conn.execute(
                        """
                        INSERT INTO relation_edges
                            (tenant_id, session_id, subject_id, predicate, object_id,
                             weight, source_turn_id, evidence, observation_count)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 1)
                        ON CONFLICT (tenant_id, session_id, subject_id, predicate, object_id)
                            WHERE invalidated_at IS NULL
                        DO UPDATE SET
                            weight            = LEAST(
                                relation_edges.weight + EXCLUDED.weight * 0.1,
                                2.0               -- cap weight at 2.0
                            ),
                            -- Repeat observation is its own signal and used to
                            -- be crushed into the weight float alongside
                            -- extraction confidence and recency.
                            observation_count = relation_edges.observation_count + 1,
                            source_turn_id    = EXCLUDED.source_turn_id,
                            evidence          = COALESCE(NULLIF(EXCLUDED.evidence, ''), relation_edges.evidence),
                            updated_at        = NOW()
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
