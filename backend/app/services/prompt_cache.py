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

from . import gemini_client
from . import persona as persona_mod

logger = logging.getLogger(__name__)

# Per-turn-kind budgets. See services/routing.py for how turn_kind is decided.
# Greetings and follow-ups do not need deep reasoning; teaching a new concept
# does. Spending the same budget on every turn made the fast cases slow.
_THINKING_BUDGETS = {"greeting": 0, "followup": 512, "opinion": 1024, "concept": 2048}
_OUTPUT_BUDGETS   = {"greeting": 512, "followup": 1536, "opinion": 2048, "concept": 3072}

# ─────────────────────────────────────────────────────────────────────────────
# ANDREW NG PERSONA PROMPT (static — perfect for caching)
# ─────────────────────────────────────────────────────────────────────────────
# Persona text, validators and learner-profile construction live in
# services/persona.py so they can be tested and reused without importing the
# generation stack.
from .persona import ANDREW_NG_PERSONA  # noqa: F401



# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PersonaCache:
    """
    Tracks the Gemini context cache holding the persona.

    Previously this cached the persona AND the retrieved RAG chunks, keyed by
    session. That was wrong in two ways. First, chunks change every turn, so
    caching turn one's chunks meant later turns read stale context labelled as
    the knowledge base while the relevant passages arrived as an afterthought.
    Second, keying by session created one Gemini cache resource per session,
    each billing storage, none ever released.

    The persona is genuinely static, so exactly one cache per API key is both
    correct and cheap.
    """
    cache_name:  str                                  # "" means no cache in use
    created_at:  float = field(default_factory=time.time)
    ttl_seconds: int   = 3600

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) >= self.ttl_seconds


@dataclass
class CacheStatus:
    """Honest reporting of what the cache actually did on this call."""
    status:        str = "uncached"   # "hit" | "miss" | "uncached"
    cached_tokens: int = 0            # from Gemini usage metadata, not inferred


@dataclass
class CachedGenerationRequest:
    """Parameters for one generation call."""
    session_id:      str
    user_message:    str
    turn_history:    list[dict[str, str]]   # prior conversational turns
    graph_context:   str                    # dynamic graph summary
    knowledge_block: str = ""               # THIS turn's retrieved passages
    learner_profile: str = ""               # calibration derived from the graph
    turn_kind:       str = "concept"        # routing hint, see services/routing.py
    temperature:     float = 0.7


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
        self._api_key = gemini_api_key
        # NOTE: no genai.configure() here. Keys are passed per call through
        # services/gemini_client.py, because module-global configuration is a
        # cross-request key leak in an async server.
        self._persona_cache: PersonaCache | None = None
        self._lock = asyncio.Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Get or create the persona context cache
    # ─────────────────────────────────────────────────────────────────────────
    async def get_or_create_cache(self, cache_ttl_seconds: int = 3600) -> PersonaCache:
        """
        Return a valid persona cache, creating one if absent or expired.

        Only the persona is cached. Retrieved passages are deliberately NOT
        cached: they are specific to a single turn's question.
        """
        async with self._lock:
            existing = self._persona_cache
            if existing and not existing.is_expired:
                return existing

            logger.info("Creating Gemini persona cache")
            self._persona_cache = await self._create_persona_cache(cache_ttl_seconds)
            return self._persona_cache

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Generate a response
    # ─────────────────────────────────────────────────────────────────────────
    async def generate(
        self,
        request: CachedGenerationRequest,
        gemini_api_key: str,
    ) -> tuple[str, CacheStatus]:
        """
        Run one generation and report what the cache actually did.

        Returns (assistant_text, CacheStatus). The status carries the real
        cached-token count from Gemini's usage metadata rather than inferring
        a hit from how long ago a Python object was constructed.
        """
        persona_cache = await self.get_or_create_cache()
        text, status = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._sync_generate(request, persona_cache, gemini_api_key),
        )

        # Enforce the mechanical persona rules rather than only asking for them.
        # The model slips on these under load even with the instruction present,
        # and the violation rate is a persona-quality metric worth tracking.
        violations = persona_mod.validate_response(text)
        if violations:
            logger.info(
                "Persona violations (%s): %s",
                request.turn_kind, persona_mod.violation_summary(violations),
            )
            repaired = persona_mod.repair_response(text)
            if repaired and repaired != text:
                remaining = persona_mod.validate_response(repaired)
                if len(remaining) < len(violations):
                    text = repaired

        return text, status

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: Drop the persona cache (e.g. on shutdown)
    # ─────────────────────────────────────────────────────────────────────────
    async def invalidate(self) -> None:
        async with self._lock:
            if self._persona_cache:
                await self._delete_cache(self._persona_cache.cache_name)
                self._persona_cache = None

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Create Gemini context cache
    # ─────────────────────────────────────────────────────────────────────────
    async def _create_persona_cache(self, ttl_seconds: int) -> PersonaCache:
        """
        Cache the persona system instruction.

        The persona is passed ONLY as system_instruction. The previous version
        also repeated the whole persona inside `contents`, so every generation
        read the same ~2500-token instruction block twice.

        Explicit caching has a per-model minimum token count. If the persona
        falls under it the call fails, and we degrade to uncached generation —
        Gemini 2.5 applies implicit prefix caching automatically anyway, and
        the prompt is ordered static-first so that still applies.
        """
        def _create() -> str:
            # Explicit caching is only wired for the legacy SDK. On google-genai
            # the equivalent API differs, and implicit prefix caching already
            # covers the persona because the prompt is ordered static-first, so
            # skipping it there costs nothing measurable.
            if gemini_client.backend_name() != "legacy":
                return ""
            from google.generativeai import caching  # type: ignore
            import google.generativeai as genai  # type: ignore
            # Same lock the generation path uses: configure() is global state.
            with gemini_client.legacy_lock():
                genai.configure(api_key=self._api_key)
                cache = caching.CachedContent.create(
                    model              = self.CACHE_SUPPORTED_MODEL,
                    system_instruction = ANDREW_NG_PERSONA,
                    ttl                = datetime.timedelta(seconds=ttl_seconds),
                    display_name       = "andrew_ng_persona",
                )
            return cache.name

        try:
            name = await asyncio.get_event_loop().run_in_executor(None, _create)
            return PersonaCache(cache_name=name, ttl_seconds=ttl_seconds)
        except Exception as e:
            logger.warning(
                "Persona cache creation failed (%s). Falling back to uncached "
                "generation; implicit caching still applies.", e
            )
            return PersonaCache(cache_name="", ttl_seconds=ttl_seconds)

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE: Synchronous generation (runs in thread pool)
    # ─────────────────────────────────────────────────────────────────────────


    async def stream(
        self,
        request: CachedGenerationRequest,
        gemini_api_key: str,
    ):
        """
        Async generator yielding text fragments as they are produced.

        Runs the blocking SDK iterator on a worker thread and hands fragments
        back through a queue, because neither Gemini SDK offers a native async
        stream and blocking the event loop would stall every other request.
        """
        persona_cache = await self.get_or_create_cache()
        budget  = _THINKING_BUDGETS.get(request.turn_kind, 2048)
        max_out = _OUTPUT_BUDGETS.get(request.turn_kind, 2048)
        messages = self._build_messages(request)

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        _SENTINEL = object()

        def _produce() -> None:
            try:
                for fragment in gemini_client.stream_sync(
                    api_key            = gemini_api_key,
                    model              = self.CACHE_SUPPORTED_MODEL,
                    contents           = messages,
                    system_instruction = persona_mod.ANDREW_NG_PERSONA,
                    temperature        = request.temperature,
                    max_output_tokens  = max_out,
                    thinking_budget    = budget,
                    cached_content     = persona_cache.cache_name or None,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, fragment)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        loop.run_in_executor(None, _produce)

        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    def _build_messages(self, request: CachedGenerationRequest) -> list[dict]:
        """
        Assemble the prompt.

        Layout is ordered so the static prefix stays byte-identical between
        requests, which is what earns the implicit prefix-cache discount:

            [system instruction: persona]   static, cached
            [conversation history]          grows, stable prefix
            [context turn: knowledge + graph + learner profile for THIS turn]
            [model ack]
            [student question]              isolated, last

        The question gets its own final turn rather than being appended to the
        end of a multi-thousand-token context block, where it competed with the
        injected material for attention.
        """
        messages: list[dict] = []

        # Prior turns. Gemini uses 'model', not 'assistant'.
        for turn in request.turn_history:
            raw_role = turn.get("role", "user")
            role = "model" if raw_role == "assistant" else raw_role
            messages.append({
                "role": role,
                "parts": [{"text": turn.get("content", "")}],
            })

        # This turn's context, rebuilt fresh every time.
        context_parts = []
        if request.knowledge_block:
            context_parts.append(request.knowledge_block)
        context_parts.append(
            f"\nSTUDENT KNOWLEDGE GRAPH CONTEXT:\n{request.graph_context}\n"
        )
        # Calibration computed from the student's whole history, rather than
        # asking the model to guess their level from a single message.
        if request.learner_profile:
            context_parts.append(f"\n{request.learner_profile}\n")
        messages.append({
            "role": "user",
            "parts": [{"text": "".join(context_parts)}],
        })
        messages.append({
            "role": "model",
            "parts": [{"text": "Understood. I have the relevant material and what I know about this student."}],
        })

        # The actual question, alone, last.
        messages.append({
            "role": "user",
            "parts": [{"text": request.user_message}],
        })

        return self._dedupe_consecutive_roles(messages)

    def _sync_generate(
        self,
        request: CachedGenerationRequest,
        persona_cache: PersonaCache,
        api_key: str,
    ) -> tuple[str, CacheStatus]:
        """
        Build the prompt and call Gemini.

        Prompt layout, ordered so the static prefix stays byte-identical across
        requests (this is what earns the implicit prefix-cache discount):

            [system instruction: persona]   static, cached
            [conversation history]          grows, stable prefix
            [context turn: knowledge + graph for THIS turn]
            [model ack]
            [student question]              isolated, last

        The question gets its own final turn instead of being appended to the
        end of a multi-thousand-token context block, where it competed with
        the injected material for attention.
        """
        messages = self._build_messages(request)

        status = CacheStatus()

        # Routing sets how much internal reasoning the turn deserves. A
        # greeting does not need a thinking budget; a new concept does.
        # Thinking tokens are drawn from the same budget as the visible answer,
        # which is why the old code raised max_output_tokens to 65536 to stop
        # answers truncating. Capping thinking directly is the actual fix and
        # lets the output ceiling return to a conversational size.
        budget = _THINKING_BUDGETS.get(request.turn_kind, 2048)
        max_out = _OUTPUT_BUDGETS.get(request.turn_kind, 2048)

        result = gemini_client.generate_sync(
            api_key            = api_key,
            model              = self.CACHE_SUPPORTED_MODEL,
            contents           = messages,
            system_instruction = persona_mod.ANDREW_NG_PERSONA,
            temperature        = request.temperature,
            max_output_tokens  = max_out,
            thinking_budget    = budget,
            cached_content     = persona_cache.cache_name or None,
        )

        status.cached_tokens = result.cached_tokens
        if persona_cache.cache_name:
            status.status = "hit" if result.cached_tokens > 0 else "miss"
        else:
            status.status = "uncached"

        return result.text, status

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
        def _delete() -> None:
            if gemini_client.backend_name() != "legacy":
                return
            from google.generativeai import caching  # type: ignore
            import google.generativeai as genai  # type: ignore
            # Same lock the generation path uses: configure() is global state.
            with gemini_client.legacy_lock():
                genai.configure(api_key=self._api_key)
                caching.CachedContent.get(cache_name).delete()

        try:
            await asyncio.get_event_loop().run_in_executor(None, _delete)
            logger.info("Deleted Gemini cache: %s", cache_name)
        except Exception as e:
            logger.warning("Failed to delete cache %s: %s", cache_name, e)
