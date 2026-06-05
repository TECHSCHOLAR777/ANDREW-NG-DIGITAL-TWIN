"""
services/prompt_cache.py
─────────────────────────────────────────────────────────────────────────────
Gemini API Context Caching for static RAG chunks + persona prompt.

Gemini's Context Caching (as of gemini-1.5-pro/flash) lets you cache a
large, static portion of the prompt (system prompt + RAG chunks) and reuse
it across multiple turns without re-tokenizing or re-billing for those tokens.

Cost model:
  - Cached tokens are billed at ~0.25× the normal input token price.
  - Cache TTL is configurable (min 1 hour, default 1 hour).
  - Ideal for: persona prompt (500 tokens) + top-K RAG chunks (8000 tokens).

This service manages a per-session cache entry. On first query it creates
the cache; subsequent queries in the same session reuse it. The cache is
invalidated when the session ends or TTL expires.

Architecture:
  Session store: in-memory dict (upgrade to Redis for multi-replica)
  Cache lifecycle: created on first message → reused for session lifetime
  Cache contents: system prompt + retrieved RAG chunks (static per session)

Dependencies:
  pip install google-generativeai
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import google.generativeai as genai
from google.generativeai import caching

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ANDREW NG PERSONA PROMPT (static — perfect for caching)
# ─────────────────────────────────────────────────────────────────────────────
ANDREW_NG_PERSONA = """
You are Andrew Ng — co-founder of Coursera, former Chief Scientist at Baidu,
founder of DeepLearning.AI, and one of the most influential AI educators alive.

PERSONALITY & STYLE:
- Calm, encouraging, and deeply patient. You celebrate small wins enthusiastically.
- You use concrete examples before abstract theory. ("Think of a neuron like a 
  logistic regression unit, but we stack thousands of them...")
- You speak in short paragraphs. You ask clarifying questions often.
- You quote from your own courses (Machine Learning Specialization, Deep Learning
  Specialization) as primary references.
- You are honest about uncertainty: "This is still an open research question..."
- You use light humor, especially self-deprecating references to your own mistakes.
- You never talk down to students. Every question deserves a thoughtful response.

KNOWLEDGE SCOPE:
- Machine learning fundamentals, deep learning, MLOps, AI strategy.
- You have deep opinions on learning paths and recommend structured curricula.
- You stay current with research but always ground it in fundamentals first.

RESPONSE FORMAT:
- Lead with the key insight in the first sentence.
- Use analogies liberally. 
- End with a concrete action item or follow-up question.
- Keep responses under 300 words unless asked for detail.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SessionCache:
    """Tracks a Gemini context cache for one user session."""
    session_id:     str
    cache_name:     str           # Gemini cache resource name
    cached_chunks:  list[str]     # chunk texts that were cached (for diffing)
    created_at:     float = field(default_factory=time.time)
    ttl_seconds:    int   = 3600  # 1 hour

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) >= self.ttl_seconds

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.created_at) / 60


@dataclass
class CachedGenerationRequest:
    """Parameters for a generation call that uses a cached context."""
    session_id:    str
    user_message:  str
    turn_history:  list[dict[str, str]]   # non-cached conversational turns
    graph_context: str                    # dynamic graph-summary (not cached)
    temperature:   float = 0.7


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT CACHE MANAGER
# ─────────────────────────────────────────────────────────────────────────────
class PromptCacheManager:
    """
    Manages Gemini context caches per user session.

    Lifecycle:
      1. User sends first message → `get_or_create_cache()` builds cache.
      2. Subsequent messages in same session → cache is reused (cheap).
      3. Cache expires after TTL or session ends → rebuilt on next message.

    What gets cached:
      - Andrew Ng persona system prompt (static, ~500 tokens)
      - Top-K RAG chunks retrieved for this session (semi-static, ~8000 tokens)

    What does NOT get cached (passed as dynamic content each turn):
      - The actual user question
      - Knowledge graph context summary (changes per turn)
      - Conversation history
    """

    # Model that supports context caching
    # gemini-2.5-pro or gemini-2.5-flash
    CACHE_SUPPORTED_MODEL = "models/gemini-2.5-flash"

    def __init__(self, gemini_api_key: str):
        genai.configure(api_key=gemini_api_key)
        # In-memory session → cache map (use Redis for multi-replica)
        self._session_caches: dict[str, SessionCache] = {}
        self._lock = asyncio.Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Get or create a context cache for this session
    # ─────────────────────────────────────────────────────────────────────────
    async def get_or_create_cache(
        self,
        session_id: str,
        rag_chunks: list[str],
        cache_ttl_seconds: int = 3600,
    ) -> SessionCache:
        """
        Returns a valid SessionCache for the session.
        Creates a new Gemini cache if:
          - No cache exists for this session
          - Existing cache has expired
          - RAG chunks have changed (content drift)
        """
        async with self._lock:
            existing = self._session_caches.get(session_id)

            # Check if existing cache is still valid
            if existing and not existing.is_expired:
                if existing.cached_chunks == rag_chunks:
                    logger.debug(
                        "Cache HIT for session %s (age=%.1fm)",
                        session_id, existing.age_minutes
                    )
                    return existing
                else:
                    logger.info("Cache STALE (chunk drift) for session %s", session_id)
                    await self._delete_cache(existing.cache_name)

            # Create a new cache
            logger.info("Creating new Gemini cache for session %s", session_id)
            session_cache = await self._create_gemini_cache(
                session_id, rag_chunks, cache_ttl_seconds
            )
            self._session_caches[session_id] = session_cache
            return session_cache

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Generate a response using the cached context
    # ─────────────────────────────────────────────────────────────────────────
    async def generate_with_cache(
        self,
        request: CachedGenerationRequest,
        gemini_api_key: str,
        rag_chunks: list[str],
    ) -> str:
        """
        Runs a generation using the cached system prompt + RAG chunks.

        The dynamic parts (graph context, conversation history, user question)
        are passed as regular message content — only the static chunks are cached.
        """
        # Ensure cache exists and is valid
        session_cache = await self.get_or_create_cache(
            request.session_id, rag_chunks
        )

        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(
            None,
            lambda: self._sync_generate(request, session_cache),
        )
        return response_text

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Invalidate session cache (call on session end)
    # ─────────────────────────────────────────────────────────────────────────
    async def invalidate_session(self, session_id: str) -> None:
        async with self._lock:
            if existing := self._session_caches.pop(session_id, None):
                await self._delete_cache(existing.cache_name)
                logger.info("Invalidated cache for session %s", session_id)

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Create Gemini context cache
    # ─────────────────────────────────────────────────────────────────────────
    async def _create_gemini_cache(
        self,
        session_id: str,
        rag_chunks: list[str],
        ttl_seconds: int,
    ) -> SessionCache:
        """
        Calls the Gemini Caching API to cache the persona + RAG chunks.

        The cached content is structured as:
          [system_prompt_part] + [rag_chunk_part_1] + ... + [rag_chunk_part_N]

        Minimum cache size: 32,768 tokens (Gemini requirement).
        If chunks are too small, pad with persona detail or use without cache.
        """

        # Build the static content to cache
        static_content_parts = [
            # Part 1: The persona
            {"text": f"PERSONA:\n{ANDREW_NG_PERSONA}\n\n"},
            # Part 2: Retrieved RAG chunks (retrieved once, reused all session)
            {"text": "KNOWLEDGE BASE:\n\n"},
        ]

        for i, chunk in enumerate(rag_chunks):
            static_content_parts.append({
                "text": f"[Chunk {i+1}]\n{chunk}\n\n"
            })

        loop = asyncio.get_event_loop()
        try:
            cache = await loop.run_in_executor(
                None,
                lambda: caching.CachedContent.create(
                    model        = self.CACHE_SUPPORTED_MODEL,
                    system_instruction = ANDREW_NG_PERSONA,
                    contents     = static_content_parts,
                    ttl          = datetime.timedelta(seconds=ttl_seconds),
                    display_name = f"andrew_ng_session_{session_id}",
                )
            )
            return SessionCache(
                session_id    = session_id,
                cache_name    = cache.name,
                cached_chunks = rag_chunks,
                ttl_seconds   = ttl_seconds,
            )

        except Exception as e:
            # If caching fails (e.g. chunk too small), fall back gracefully
            logger.warning(
                "Cache creation failed (likely too few tokens): %s. "
                "Falling back to uncached generation.", e
            )
            # Return a dummy SessionCache with empty name to signal fallback
            return SessionCache(
                session_id    = session_id,
                cache_name    = "",   # empty = no cache
                cached_chunks = rag_chunks,
                ttl_seconds   = ttl_seconds,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Synchronous generation (runs in thread pool)
    # ─────────────────────────────────────────────────────────────────────────
    def _sync_generate(
        self,
        request: CachedGenerationRequest,
        session_cache: SessionCache,
    ) -> str:
        """Builds the dynamic prompt and calls Gemini with or without cache."""

        # Build dynamic message content (NOT cached):
        #   - Knowledge graph context (changes each turn)
        #   - Conversation history
        #   - Current user message
        messages: list[dict] = []

        # Add prior turns from conversation history
        # Map 'assistant' → 'model' for Gemini compatibility
        for turn in request.turn_history:
            raw_role = turn.get("role", "user")
            role = "model" if raw_role == "assistant" else raw_role
            messages.append({
                "role": role,
                "parts": [{"text": turn.get("content", "")}],
            })

        # Inject graph context into the user's message
        user_content_with_graph = (
            f"STUDENT KNOWLEDGE GRAPH CONTEXT:\n"
            f"{request.graph_context}\n\n"
            f"STUDENT QUESTION:\n{request.user_message}"
        )
        messages.append({
            "role": "user",
            "parts": [{"text": user_content_with_graph}],
        })

        gen_config = genai.GenerationConfig(
            temperature    = request.temperature,
            max_output_tokens = 1024,
        )

        # ── WITH CACHE ──────────────────────────────────────────────────────
        if session_cache.cache_name:
            cached_content = caching.CachedContent.get(session_cache.cache_name)
            model = genai.GenerativeModel.from_cached_content(
                cached_content   = cached_content,
                generation_config= gen_config,
            )
            # Ensure no consecutive same-role messages
            messages = self._dedupe_consecutive_roles(messages)
            response = model.generate_content(messages)

        # ── FALLBACK (no cache) ─────────────────────────────────────────────
        else:
            logger.debug("Generating without cache for session %s", request.session_id)
            chunks_text = "\n\n".join(
                f"[Chunk {i+1}]\n{c}"
                for i, c in enumerate(session_cache.cached_chunks)
            )
            model = genai.GenerativeModel(
                model_name          = self.CACHE_SUPPORTED_MODEL,
                system_instruction  = ANDREW_NG_PERSONA,
                generation_config   = gen_config,
            )
            # Prepend the RAG chunks as the first message
            full_messages = [
                {"role": "user", "parts": [{"text": f"KNOWLEDGE BASE:\n{chunks_text}"}]},
                {"role": "model", "parts": [{"text": "Understood. I have the knowledge base loaded."}]},
            ] + messages
            # Ensure no consecutive same-role messages
            full_messages = self._dedupe_consecutive_roles(full_messages)
            response = model.generate_content(full_messages)

        return response.text

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Deduplicate consecutive same-role messages
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _dedupe_consecutive_roles(messages: list[dict]) -> list[dict]:
        """
        Gemini rejects conversations with consecutive messages of the same role.
        This merges them by concatenating their text content.
        """
        if not messages:
            return messages

        deduped: list[dict] = [messages[0]]
        for msg in messages[1:]:
            if msg["role"] == deduped[-1]["role"]:
                # Merge text parts into the previous message
                prev_text = deduped[-1]["parts"][0]["text"]
                curr_text = msg["parts"][0]["text"]
                deduped[-1]["parts"][0]["text"] = prev_text + "\n\n" + curr_text
            else:
                deduped.append(msg)
        return deduped

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Delete a Gemini cache
    # ─────────────────────────────────────────────────────────────────────────
    async def _delete_cache(self, cache_name: str) -> None:
        if not cache_name:
            return
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: caching.CachedContent.get(cache_name).delete()
            )
            logger.info("Deleted Gemini cache: %s", cache_name)
        except Exception as e:
            logger.warning("Failed to delete cache %s: %s", cache_name, e)
