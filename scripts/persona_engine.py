"""
persona_engine.py — Andrew Ng Digital Twin Core Runtime Engine
==============================================================
Full RAG + Persona pipeline:
  Query → Domain Classify + Query Expand (1 Gemini call)
  → Hybrid Retrieve (BM25 + Vector + Domain Filter)
  → Cross-Encoder Rerank → Persona Filter Assembly
  → Gemini 2.5 Flash → Post-Processing Style Check
  → Background Memory Update

Dependencies:
  Required : chromadb, sentence-transformers, google-generativeai, python-dotenv
  Optional : rank_bm25 (hybrid retrieval), numpy (scoring)
"""

import os
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from dotenv import load_dotenv
import google.generativeai as genai

# Optional dependencies — graceful fallback if missing
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder
    HAS_CROSS_ENCODER = True
except ImportError:
    HAS_CROSS_ENCODER = False


# Load environment variables
load_dotenv()

# ================================================================================
# Constants & File Paths
# ================================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "chroma_db"
MEMORY_DIR = PROJECT_ROOT / "data" / "memory"
USER_PROFILE_PATH = MEMORY_DIR / "user_profile.json"
EPISODIC_MEMORY_PATH = MEMORY_DIR / "episodic_memory.json"
COLLECTION_NAME = "andrew_ng_digital_twin"
MODEL_NAME = "all-MiniLM-L6-v2"
LLM_MODEL_NAME = "gemini-2.5-flash"
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"

VALID_DOMAINS = ["ml_theory", "deep_learning", "ai_strategy", "career_advice", "agentic_ai"]
EPISODIC_MEMORY_LIMIT = 250
SESSION_MEMORY_TURN_LIMIT = 8
RETRIEVED_MEMORY_LIMIT = 5

# Ensure directories exist
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

_embedding_function = None

def _get_embedding_function():
    """Cached singleton for sentence transformer embedding function."""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
    return _embedding_function

# ================================================================================
# Gemini Key Rotation
# ================================================================================

KEY_COOLDOWN_SECONDS = 90


def _load_gemini_api_keys() -> list[str]:
    """Loads Gemini keys from singular and numbered env vars, preserving order."""
    keys = []

    for var_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(var_name, "").strip()
        if value and value not in keys:
            keys.append(value)

    for prefix in ("GEMINI_API_KEY_", "GOOGLE_API_KEY_"):
        indexed = []
        for env_name, value in os.environ.items():
            if not env_name.startswith(prefix):
                continue
            suffix = env_name[len(prefix):]
            if suffix.isdigit():
                indexed.append((int(suffix), value.strip()))

        for _, value in sorted(indexed, key=lambda item: item[0]):
            if value and value not in keys:
                keys.append(value)

    return keys


class GeminiKeyManager:
    """Thread-safe round-robin Gemini key manager with temporary cooldowns."""

    def __init__(self, keys: list[str], cooldown_seconds: int = KEY_COOLDOWN_SECONDS):
        self.keys = keys
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._cursor = 0
        self._cooldowns: dict[str, float] = {}

    def has_keys(self) -> bool:
        return bool(self.keys)

    def _available_keys(self, now: float) -> list[str]:
        return [
            key for key in self.keys
            if self._cooldowns.get(key, 0.0) <= now
        ]

    def acquire_candidates(self) -> list[str]:
        """Returns keys in round-robin order, preferring keys not on cooldown."""
        if not self.keys:
            return []

        with self._lock:
            now = time.time()
            available = self._available_keys(now)
            ordered_pool = available or self.keys
            start = self._cursor % len(ordered_pool)
            ordered = ordered_pool[start:] + ordered_pool[:start]

            if ordered_pool:
                self._cursor = (start + 1) % len(ordered_pool)

            return ordered

    def mark_success(self, key: str):
        with self._lock:
            self._cooldowns.pop(key, None)

    def mark_failure(self, key: str):
        with self._lock:
            self._cooldowns[key] = time.time() + self.cooldown_seconds


_gemini_key_manager = GeminiKeyManager(_load_gemini_api_keys())
_gemini_call_lock = threading.Lock()


def has_gemini_api_key() -> bool:
    return _gemini_key_manager.has_keys()


def _should_retry_with_next_key(exc: Exception) -> bool:
    """Retry on rate/auth/transient quota issues; keep other failures visible."""
    message = str(exc).lower()
    retry_markers = [
        "429",
        "quota",
        "rate limit",
        "resource has been exhausted",
        "too many requests",
        "api key not valid",
        "permission denied",
        "deadline exceeded",
        "timed out",
        "unavailable",
    ]
    return any(marker in message for marker in retry_markers)


def gemini_generate_content(
    *,
    model_name: str,
    contents: Any,
    system_instruction: str | None = None,
    generation_config: Any = None,
):
    """
    Executes a Gemini request using round-robin keys with cooldowns on failures.
    We lock configure+generate together because google-generativeai uses global config.
    """
    candidate_keys = _gemini_key_manager.acquire_candidates()
    if not candidate_keys:
        raise RuntimeError(
            "Gemini API key is missing. Configure GEMINI_API_KEY or GEMINI_API_KEY_1..N in .env."
        )

    last_error = None

    for idx, key in enumerate(candidate_keys):
        try:
            with _gemini_call_lock:
                genai.configure(api_key=key)
                model_kwargs = {"model_name": model_name}
                if system_instruction is not None:
                    model_kwargs["system_instruction"] = system_instruction

                model = genai.GenerativeModel(**model_kwargs)
                if generation_config is None:
                    response = model.generate_content(contents)
                else:
                    response = model.generate_content(
                        contents,
                        generation_config=generation_config,
                    )

            _gemini_key_manager.mark_success(key)
            return response

        except Exception as exc:
            last_error = exc
            if _should_retry_with_next_key(exc):
                _gemini_key_manager.mark_failure(key)
                if idx < len(candidate_keys) - 1:
                    continue
            raise

    if last_error is not None:
        raise last_error

    raise RuntimeError("Gemini request failed before a model call could be completed.")

# ================================================================================
# Lazy-Loaded Global Caches (BM25 Index + Cross-Encoder)
# ================================================================================

_bm25_cache = {
    "index": None,
    "documents": None,
    "metadatas": None,
    "ids": None,
    "loaded": False,
}

_cross_encoder_model = None


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer for BM25 — lowercase, alphanumeric tokens."""
    return re.findall(r"\b\w+\b", text.lower())


def _ensure_bm25_loaded() -> bool:
    """Lazy-build BM25 index from all Chroma documents on first call."""
    global _bm25_cache
    if _bm25_cache["loaded"]:
        return True
    if not HAS_BM25 or not HAS_NUMPY:
        return False
    if not DB_PATH.exists():
        return False

    try:
        client = chromadb.PersistentClient(path=str(DB_PATH))
        ef = _get_embedding_function()
        collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)

        all_data = collection.get(include=["documents", "metadatas"])
        docs = all_data["documents"]
        metas = all_data["metadatas"]
        ids = all_data["ids"]

        if not docs:
            return False

        tokenized_corpus = [_tokenize(doc) for doc in docs]
        bm25_index = BM25Okapi(tokenized_corpus)

        _bm25_cache.update({
            "index": bm25_index,
            "documents": docs,
            "metadatas": metas,
            "ids": ids,
            "loaded": True,
        })
        return True
    except Exception as e:
        print(f"[BM25] Warning: could not build index — {e}")
        return False


def _get_cross_encoder():
    """Lazy-load the cross-encoder reranker model."""
    global _cross_encoder_model
    if _cross_encoder_model is not None:
        return _cross_encoder_model
    if not HAS_CROSS_ENCODER:
        return None
    try:
        _cross_encoder_model = _CrossEncoder(CROSS_ENCODER_MODEL)
        return _cross_encoder_model
    except Exception as e:
        print(f"[Reranker] Warning: could not load cross-encoder — {e}")
        return None


# ================================================================================
# Memory Schema & Management
# ================================================================================

DEFAULT_PROFILE = {
    "student_profile": {
        "identity": "unknown",
        "industry_domain": "unknown",
        "mathematical_comfort_level": "unknown",
    },
    "career_and_business_goals": {
        "short_term": "unknown",
        "long_term": "unknown",
    },
    "misconceptions_and_focus_areas": [],
    "learning_preferences": {
        "explanation_style": "unknown",
    },
    "topics_discussed_timeline": [],
    "personal_rapport": {
        "name": "unknown",
        "location": "unknown",
        "notable_remarks": [],
    },
}

DEFAULT_EPISODIC_MEMORY = {
    "version": 1,
    "entries": [],
}


def load_episodic_memory_store() -> dict:
    """Loads cross-session episodic memory, initializing the file if needed."""
    if not EPISODIC_MEMORY_PATH.exists():
        with open(EPISODIC_MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_EPISODIC_MEMORY, f, indent=2)
        return json.loads(json.dumps(DEFAULT_EPISODIC_MEMORY))

    try:
        with open(EPISODIC_MEMORY_PATH, "r", encoding="utf-8") as f:
            store = json.load(f)
        if not isinstance(store, dict) or "entries" not in store:
            return json.loads(json.dumps(DEFAULT_EPISODIC_MEMORY))
        store.setdefault("version", 1)
        store["entries"] = [
            entry for entry in store.get("entries", [])
            if isinstance(entry, dict) and entry.get("memory")
        ]
        return store
    except Exception:
        return json.loads(json.dumps(DEFAULT_EPISODIC_MEMORY))


def save_episodic_memory_store(store: dict):
    """Persists episodic memory entries to disk."""
    with open(EPISODIC_MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def _dedupe_memory_list(values: list[str], limit: int = 10) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped


def _conversation_turn_text(chat_history: list[dict], limit: int = SESSION_MEMORY_TURN_LIMIT) -> str:
    """Formats recent turns into a compact short-term memory block."""
    if not chat_history:
        return "No earlier turns in this session yet."

    turns = chat_history[-limit:]
    lines = []
    for idx, turn in enumerate(turns, start=1):
        role = "Student" if turn.get("role") == "user" else "Andrew"
        text = " ".join(str(turn.get("content", "")).split())
        if len(text) > 220:
            text = text[:217] + "..."
        lines.append(f"- Turn {idx} {role}: {text}")
    return "\n".join(lines)


def _score_memory_entry(entry: dict, query_tokens: set[str]) -> float:
    memory_text = entry.get("memory", "")
    memory_tokens = set(_tokenize(memory_text))
    overlap = len(query_tokens & memory_tokens)
    if overlap == 0:
        return 0.0

    score = float(overlap)
    tags = [tag.lower() for tag in entry.get("tags", []) if isinstance(tag, str)]
    topic = str(entry.get("topic", "")).lower()
    if any(token in tags for token in query_tokens):
        score += 1.5
    if topic and any(token in topic for token in query_tokens):
        score += 1.0
    score += min(float(entry.get("importance", 1)), 3.0) * 0.4
    return score


def retrieve_relevant_episodic_memories(query: str, limit: int = RETRIEVED_MEMORY_LIMIT) -> list[dict]:
    """Retrieves cross-session memories relevant to the current query."""
    store = load_episodic_memory_store()
    entries = store.get("entries", [])
    if not entries:
        return []

    query_lower = query.lower()
    generic_memory_triggers = [
        "who am i", "about me", "remember me", "my name", "my background",
        "what do you know", "what did we talk", "previous conversation",
        "our last chat", "last session", "my project", "my goals", "what i do"
    ]
    is_generic_query = any(trigger in query_lower for trigger in generic_memory_triggers)

    if is_generic_query:
        # Return most important and recent memories directly
        return entries[:limit]

    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    scored = []
    for entry in entries:
        score = _score_memory_entry(entry, query_tokens)
        if score > 0:
            scored.append((score, entry))

    scored.sort(
        key=lambda item: (
            item[0],
            item[1].get("timestamp", ""),
        ),
        reverse=True,
    )
    return [entry for _, entry in scored[:limit]]


def format_episodic_memory_for_prompt(entries: list[dict]) -> str:
    """Formats retrieved long-term memories into prompt-safe bullets."""
    if not entries:
        return "No relevant cross-session memories retrieved yet."

    bullets = []
    for entry in entries:
        topic = entry.get("topic") or "General"
        memory = entry.get("memory", "")
        kind = entry.get("memory_type", "memory")
        bullets.append(f"- [{kind}] {topic}: {memory}")
    return "\n".join(bullets)


def load_user_profile() -> dict:
    """Loads the stored student profile from local storage, initializing it if empty."""
    if not USER_PROFILE_PATH.exists():
        with open(USER_PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PROFILE, f, indent=2)
        return DEFAULT_PROFILE.copy()

    try:
        with open(USER_PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_PROFILE.copy()


def save_user_profile(profile: dict):
    """Saves the student profile safely back to user_profile.json."""
    with open(USER_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)


def reset_user_profile():
    """Wipes profile and long-term memory, resetting to the default schema."""
    save_user_profile(DEFAULT_PROFILE)
    save_episodic_memory_store(DEFAULT_EPISODIC_MEMORY)


def format_memory_for_prompt(profile: dict) -> str:
    """Formats the rich profile JSON into a text block for the LLM system prompt."""
    sp = profile.get("student_profile", {})
    goals = profile.get("career_and_business_goals", {})
    misconceptions = profile.get("misconceptions_and_focus_areas", [])
    pref = profile.get("learning_preferences", {})
    rapport = profile.get("personal_rapport", {})
    timeline = profile.get("topics_discussed_timeline", [])

    bullets = []

    # Core student details
    bullets.append(f"- Student Identity: {sp.get('identity', 'unknown')} (Industry: {sp.get('industry_domain', 'unknown')})")
    bullets.append(f"- Mathematical Comfort Level: {sp.get('mathematical_comfort_level', 'unknown')}")

    # Career goals
    bullets.append(f"- Stated Short-Term Goal: {goals.get('short_term', 'unknown')}")
    bullets.append(f"- Stated Long-Term Goal: {goals.get('long_term', 'unknown')}")

    # Learning preference
    bullets.append(f"- Preferred Explanation Style: {pref.get('explanation_style', 'unknown')}")

    # Personal rapport
    if rapport.get("name") != "unknown":
        bullets.append(f"- Student Name: {rapport.get('name')}")
    if rapport.get("location") != "unknown":
        bullets.append(f"- Location: {rapport.get('location')}")

    for remark in rapport.get("notable_remarks", []):
        bullets.append(f"- Personal Context: {remark}")

    # Misconceptions
    for mis in misconceptions:
        bullets.append(f"- Concept to Revisit/Clarify: {mis}")

    # Past subjects
    if timeline:
        topics = ", ".join(t.get("topic", "") for t in timeline[-5:])
        bullets.append(f"- Recently Discussed Subjects: {topics}")

    return "\n".join(bullets)


# ================================================================================
# Domain Classifier + Query Expansion (Combined — 1 Gemini Call)
# ================================================================================

CLASSIFY_EXPAND_PROMPT = """\
You are a query router for an Andrew Ng Digital Twin.

TASK — analyse the student's query and return a JSON object with exactly two keys:
1. "domain": classify into exactly ONE of: ml_theory, deep_learning, ai_strategy, career_advice, agentic_ai
2. "expanded_query": rewrite the query using Andrew Ng's vocabulary and pedagogical register. Include his canonical terms (e.g. housing prices, spam classifier, cat recognition, J(θ), bias-variance, error analysis) where relevant. Keep it under 60 words.

Student background:
{student_context}

Student query:
{query}

Return ONLY raw JSON. No markdown, no explanation."""


def classify_and_expand_query(query: str, student_context: str) -> tuple[str, str]:
    """
    One fast Gemini call that returns (domain, expanded_query).
    Falls back to ("ai_strategy", original_query) on any failure.
    """
    if not has_gemini_api_key():
        return "ai_strategy", query

    prompt = CLASSIFY_EXPAND_PROMPT.format(student_context=student_context, query=query)

    try:
        resp = gemini_generate_content(
            model_name=LLM_MODEL_NAME,
            contents=prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=200,
            ),
        )
        text = resp.text.strip()

        # Strip markdown wrapping
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)
        domain = result.get("domain", "ai_strategy")
        expanded = result.get("expanded_query", query)

        # Validate domain
        if domain not in VALID_DOMAINS:
            domain = "ai_strategy"

        return domain, expanded

    except Exception:
        return "ai_strategy", query


# ================================================================================
# Hybrid Retrieval: Domain-Filtered Vector + BM25 + Cross-Encoder Reranking
# ================================================================================

def _reciprocal_rank_fusion(ranked_id_lists: list[list[str]], k: int = 60) -> list[str]:
    """Fuse multiple ranked ID lists via Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    for id_list in ranked_id_lists:
        for rank, doc_id in enumerate(id_list):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


def _source_quality_boost(meta: dict) -> float:
    """
    Bias retrieval toward Andrew's highest-fidelity voice sources.
    This helps even before re-ingestion adds richer metadata.
    """
    doc_type = str(meta.get("doc_type", "")).lower()
    source = str(meta.get("source", "")).lower()
    title = str(meta.get("title", "")).lower()

    boost = 0.0
    if "source_authority" in meta:
        try:
            boost += float(meta["source_authority"]) * 2.0
        except Exception:
            pass
    if doc_type == "pdfs":
        boost += 2.0
    elif doc_type == "transcripts":
        boost += 1.8
    elif doc_type == "the_batch":
        boost += 0.9
    elif doc_type == "blog_posts":
        boost += 0.3

    if meta.get("canonical_example"):
        boost += 0.5

    # Downweight adjacent content that is less representative of Andrew's direct voice.
    lower_quality_markers = [
        "ambassador spotlight",
        "heroes of deep learning",
        "hodl",
        "working ai",
    ]
    if any(marker in title or marker in source for marker in lower_quality_markers):
        boost -= 0.8

    return boost


def retrieve_rag_context(
    query: str,
    n_results: int = 4,
    domain: str | None = None,
    expanded_query: str | None = None,
) -> tuple[str, list[dict], bool]:
    """
    Hybrid retrieval pipeline:
      1. Domain-filtered vector search  (top-15 in-domain + top-5 cross-domain)
      2. BM25 keyword search            (top-15 over full corpus)
      3. Reciprocal Rank Fusion          (merge + deduplicate)
      4. Cross-encoder reranking         (top-N candidates → top-4)
    Falls back gracefully when optional dependencies are missing.
    """
    if not DB_PATH.exists():
        return "RAG database is not populated yet.", [], False

    search_query = expanded_query or query

    # ------------------------------------------------------------------
    # Step 1: Vector retrieval from Chroma
    # ------------------------------------------------------------------
    try:
        chroma_client = chromadb.PersistentClient(path=str(DB_PATH))
        embedding_function = _get_embedding_function()
        collection = chroma_client.get_collection(
            name=COLLECTION_NAME, embedding_function=embedding_function
        )

        # 1a. Domain-filtered vector search
        vector_ids_domain = []
        if domain and domain in VALID_DOMAINS:
            try:
                domain_results = collection.query(
                    query_texts=[search_query],
                    n_results=15,
                    where={"domain": domain},
                )
                if domain_results and domain_results["ids"] and domain_results["ids"][0]:
                    vector_ids_domain = domain_results["ids"][0]
            except Exception:
                pass

        # 1b. Cross-domain vector search (unfiltered)
        cross_results = collection.query(
            query_texts=[search_query],
            n_results=max(5, n_results) if vector_ids_domain else 20,
        )
        vector_ids_cross = cross_results["ids"][0] if cross_results and cross_results["ids"] else []

        # Combine vector IDs (domain-filtered first, then cross-domain)
        vector_ids = vector_ids_domain + [
            vid for vid in vector_ids_cross if vid not in vector_ids_domain
        ]

    except Exception as e:
        return f"Error during vector retrieval: {e}", [], False

    # ------------------------------------------------------------------
    # Step 2: BM25 keyword search
    # ------------------------------------------------------------------
    bm25_ids = []
    if _ensure_bm25_loaded():
        try:
            tokenized_query = _tokenize(search_query)
            scores = _bm25_cache["index"].get_scores(tokenized_query)
            top_indices = np.argsort(scores)[::-1][:15]
            bm25_ids = [_bm25_cache["ids"][i] for i in top_indices if scores[i] > 0]
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Step 3: Reciprocal Rank Fusion
    # ------------------------------------------------------------------
    ranked_lists = [lst for lst in [vector_ids, bm25_ids] if lst]
    if not ranked_lists:
        return "No matching grounding documents found.", [], False

    fused_ids = _reciprocal_rank_fusion(ranked_lists)

    # ------------------------------------------------------------------
    # Step 4: Fetch full documents for top candidates
    # ------------------------------------------------------------------
    candidate_limit = min(len(fused_ids), 12)  # fetch up to 12 for reranking
    candidate_ids = fused_ids[:candidate_limit]

    try:
        fetched = collection.get(ids=candidate_ids, include=["documents", "metadatas"])
    except Exception as e:
        return f"Error fetching documents: {e}", [], False

    if not fetched or not fetched["documents"]:
        return "No grounding documents found after fusion.", [], False

    # Build lookup by ID (preserves ordering from Chroma response)
    id_to_doc = {}
    id_to_meta = {}
    for cid, doc, meta in zip(fetched["ids"], fetched["documents"], fetched["metadatas"]):
        id_to_doc[cid] = doc
        id_to_meta[cid] = meta

    # Reorder candidates by fusion rank
    ordered_ids = [cid for cid in candidate_ids if cid in id_to_doc]

    # ------------------------------------------------------------------
    # Step 5: Cross-encoder reranking
    # ------------------------------------------------------------------
    cross_enc = _get_cross_encoder()
    if cross_enc and len(ordered_ids) > n_results:
        try:
            pairs = [(query, id_to_doc[cid]) for cid in ordered_ids]
            ce_scores = cross_enc.predict(pairs)
            scored = sorted(
                zip(ordered_ids, ce_scores),
                key=lambda item: item[1] + _source_quality_boost(id_to_meta[item[0]]),
                reverse=True,
            )
            ordered_ids = [cid for cid, _ in scored[:n_results]]
        except Exception:
            ordered_ids = ordered_ids[:n_results]
    else:
        ordered_ids = sorted(
            ordered_ids,
            key=lambda cid: _source_quality_boost(id_to_meta[cid]),
            reverse=True,
        )[:n_results]

    # ------------------------------------------------------------------
    # Step 6: Build output context + citations
    # ------------------------------------------------------------------
    context_chunks = []
    citations = []
    has_canonical = False

    for idx, cid in enumerate(ordered_ids):
        doc = id_to_doc[cid]
        meta = id_to_meta[cid]

        source = meta.get("source", "unknown")
        doc_type = meta.get("doc_type", "unknown")
        title = meta.get("title", "unknown")
        domain_tag = meta.get("domain", "unknown")
        is_canonical = meta.get("canonical_example", False)

        if is_canonical:
            has_canonical = True

        header = f"=== GROUNDING BLOCK #{idx + 1} | Source: {source} ({doc_type}) | Domain: {domain_tag} ==="
        context_chunks.append(f"{header}\n{doc}\n{'=' * 42}")

        citations.append({
            "source": source,
            "doc_type": doc_type,
            "title": title,
            "domain": domain_tag,
            "url": meta.get("url", "unknown"),
            "canonical_example": is_canonical,
        })

    return "\n\n".join(context_chunks), citations, has_canonical


# ================================================================================
# System Prompt — Andrew Ng Emulation
# ================================================================================

SYSTEM_INSTRUCTIONS = """\
You are Andrew Ng, the famous AI researcher and educator. You are talking directly to the student in your own voice. Speak as yourself, using first-person ("I", "we", "my", "I think", "I find").

=== CONSTRAINTS & PSYCHOLOGY ===
1. **150-WORD LIMIT**: Your response MUST be under 150 words, unless the student explicitly asks for a detailed breakdown or a comprehensive explanation. Keep it concise, natural, and efficient to save tokens.
2. **EXAMPLE-FIRST, DEFINITION-SECOND**: Never open an explanation with a formal definition (e.g., "X is an algorithm that..." or "X is defined as..."). Always open with a concrete scenario, everyday analogy, or real-world problem (e.g., "Say you're predicting house prices..." or "Imagine walking downhill in a fog..."). Only define and formalize the concept *after* the student has a mental picture.
3. **NATURAL PEDAGOGY**: Talk like a real human teacher. Do NOT use a rigid, identical structure (like Step 1, Step 2, Step 3, Step 4) for every single response. When explaining concepts:
   - Use concrete hooks or physical analogies (Lego bricks, walking down a hill in fog, pandas) naturally when explaining complex math/concepts.
   - Use a warm, encouraging, collegiate, and unhurried academic tone.
   - Use "I think" for personal views, "I find" for practitioner observations.
4. **PRACTICAL OPTIMISM**: Maintain a measured, optimistic tone. Do not endorse apocalyptic AI risk narratives ("killer robots is like worrying about overpopulation on Mars"). Discuss practical issues like economic reskilling, job displacement, and building solutions.
5. **NUMBER YOUR STEPS NATURALLY**: If giving a list, declare the count first: "There are two things I'd recommend. First... Second..." But only do this when listing items, not for standard chat text.
6. **TARGETED COMPREHENSION CHECK**: Never check understanding with generic phrases like "Does that make sense?" or "Does that help?". End explanations with a targeted check-in or simple checking question (e.g., "So if we did X, what would you expect to see?" or "If we doubled the learning rate, what would happen?").
7. **USE ACTIVE STUDENT MEMORY**: You have access to the active student profile (their identity, goals, comfort level) and episodic memories from past chats. Use this context to personalize your responses. If they ask what you know about them or ask a follow-up related to prior chats, reference these details naturally (e.g., "Since you are working in Fintech..." or "In our previous chat, you mentioned..."). Show that you remember them.

=== ANTI-PATTERNS (NEVER DO THESE) ===
- Never open with a definition or general statement (e.g., "Gradient descent is an algorithm..."). Always lead with the concrete example/analogy first.
- Never say "Obviously", "Clearly", "It's just...", or "As everyone knows."
- Never say "Great question!" or "That's a really interesting point!" as empty openers — start with substance.
- Never take AI existential-risk concerns seriously as near-term threats.
- Never use passive voice to avoid attribution — say "I think" or "I find", not "it has been proposed."
- Never end advice with "so think carefully about X" — always close with an action step.

=== HOW TO USE THE GROUNDING CONTEXT ===
- Ground your assertions entirely in the retrieved sources. Cite them naturally: "As I wrote in Machine Learning Yearning...", "In our CS229 notes...", "In The Batch..."
- If retrieved context contains one of your iconic canonical examples (housing prices, spam classification, cat recognition, Lego bricks), use that exact example.

=== TEMPORAL AWARENESS ===
Your corpus covers 2000–2026. For very recent developments not well-covered in your retrieved sources, use these hedging phrases:
- "I haven't published directly on this yet, but based on the patterns I've been tracking..."
- "My instinct, given what I've seen in agentic AI, would be..."
- "This is evolving fast — here's how I'd think about it with what I know..."

=== ACTIVE STUDENT PROFILE (MEMORY) ===
{STUDENT_MEMORY}

=== SHORT-TERM SESSION MEMORY ===
{SESSION_MEMORY}

=== LONG-TERM CROSS-SESSION MEMORY ===
{EPISODIC_MEMORY}
"""



# ================================================================================
# LLM Execution Interface — Full Pipeline
# ================================================================================

def generate_digital_twin_response(
    user_query: str, chat_history: list[dict] = None
) -> tuple[str, list[dict]]:
    """
    Full pipeline:
      1. Load user memory
      2. Domain-classify + query-expand  (1 Gemini call)
      3. Hybrid retrieve (BM25 + vector + domain filter + cross-encoder rerank)
      4. Assemble persona prompt
      5. Generate response                (1 Gemini call)
      6. Post-processing style check      (conditional Gemini call)
      7. Background memory update          (async Gemini call)
    """
    if not has_gemini_api_key():
        return (
            "Error: Gemini API key is missing. Please configure GEMINI_API_KEY or GEMINI_API_KEY_1..N in your .env file.",
            [],
        )

    if chat_history is None:
        chat_history = []

    # 1. Load active student memory
    profile = load_user_profile()
    student_memory_str = format_memory_for_prompt(profile)
    session_memory_str = _conversation_turn_text(chat_history)
    episodic_memories = retrieve_relevant_episodic_memories(user_query)
    episodic_memory_str = format_episodic_memory_for_prompt(episodic_memories)

    # 2. Bypassed domain classification + query expansion call to optimize API rate usage
    domain, expanded_query = None, None

    # 3. Hybrid RAG retrieval
    rag_context, citations, has_canonical = retrieve_rag_context(
        query=user_query,
        n_results=4,
        domain=domain,
        expanded_query=expanded_query,
    )

    # 4. Assemble system prompt with memory
    system_prompt = SYSTEM_INSTRUCTIONS.format(
        STUDENT_MEMORY=student_memory_str,
        SESSION_MEMORY=session_memory_str,
        EPISODIC_MEMORY=episodic_memory_str,
    )

    # Inject canonical example anchoring signal
    if has_canonical:
        system_prompt += (
            "\n\n💡 CRITICAL: Your retrieval surfaced one of your iconic canonical analogies "
            "(e.g., Lego bricks, housing prices, spam classifier, overpopulation on Mars). "
            "Make sure to naturally incorporate this EXACT analogy into your response!"
        )

    # 5. Compile conversation contents for Gemini
    grounding_prefix = (
        f"=== GROUNDING CONTEXT FROM RETRIEVED SOURCES ===\n"
        f"{rag_context}\n"
        f"{'=' * 50}\n"
    )

    contents = []
    for turn in chat_history[-8:]:  # Sliding window of last 8 turns
        contents.append({
            "role": "user" if turn["role"] == "user" else "model",
            "parts": [turn["content"]],
        })

    contents.append({
        "role": "user",
        "parts": [f"{grounding_prefix}\nStudent Query: {user_query}"],
    })

    # Generate response
    try:
        response = gemini_generate_content(
            model_name=LLM_MODEL_NAME,
            system_instruction=system_prompt,
            contents=contents,
        )
        response_text = response.text
    except Exception as e:
        try:
            fallback_contents = (
                f"{system_prompt}\n\n{grounding_prefix}\nStudent Query: {user_query}"
            )
            response = gemini_generate_content(
                model_name=LLM_MODEL_NAME,
                contents=fallback_contents,
            )
            response_text = response.text
        except Exception as fallback_error:
            response_text = f"Error generating response: {fallback_error or e}"

    # 6. Post-processing persona voice check
    response_text = _enhanced_post_process_voice_alignment(response_text, user_query)

    # 7. Background dynamic memory update (non-blocking daemon thread)
    try:
        memory_thread = threading.Thread(
            target=update_user_profile_dynamically,
            args=(user_query, response_text, profile),
        )
        memory_thread.daemon = True
        memory_thread.start()
    except Exception:
        pass  # Fail silently — never break the chat turn for memory

    return response_text, citations


# ================================================================================
# Post-Processing Voice Guardrails (Gemini-Powered Retry)
# ================================================================================

# Regex patterns for Ng's opening hooks
_HOOK_PATTERNS = re.compile(
    r"(?:imagine|say you|suppose|let me give you|picture this|think of|"
    r"let's say|so let's start|so one of the|it turns out|"
    r"the way I like to think|let me start with|here's a concrete|"
    r"so say you're|let me walk you through)",
    re.IGNORECASE,
)

# Phrases that signal the "key intuition" closing
_INTUITION_MARKERS = [
    "key intuition", "key insight", "key idea", "key point",
    "main takeaway", "takeaway", "what this really means",
    "so what this means", "the main thing",
]

_STEP_ENUMERATION_PATTERNS = [
    r"\bthere are (?:two|three|four|five|six|\d+) things\b",
    r"\bfirst\b.*\bsecond\b",
    r"\b1\.\s",
]

_COMPREHENSION_CHECK_PATTERNS = [
    r"\bright\?\b",
    r"\bwhat do you think would happen\b",
    r"\bwhat would you expect to see\b",
    r"\bdoes that suggest\b",
    r"\bso given that[, ]",
]

_GENERIC_CHATBOT_OPENERS = [
    "great question",
    "that's a really interesting point",
    "interesting question",
]


def _enhanced_post_process_voice_alignment(text: str, query: str) -> str:
    """
    Applies minimal style post-processing.
    Specifically checks for post-corpus queries and injects a temporal hedge parenthetical if missing.
    Bypasses Gemini rewrites and manual structure appending to keep dialogue natural and save API tokens.
    """
    query_lower = query.lower()
    text_lower = text.lower()

    if any(kw in query_lower for kw in ["2026", "2027", "2028", "2029", "2030", "gpt-5", "llama 4", "claude 3.5", "gemini 2"]):
        has_temporal_hedge = any(
            phrase in text_lower
            for phrase in [
                "beyond my current corpus",
                "beyond the current corpus",
                "haven't published directly",
                "pattern i",
                "patterns i"
            ]
        )
        if not has_temporal_hedge:
            text = "*(Note: This discusses developments beyond my current corpus, which extends to early 2026. However, based on the general patterns I've been tracking...)*\n\n" + text

    return text

STYLE_REWRITE_PROMPT = """\
You are Andrew Ng's voice editor. The response below is factually correct but needs voice adjustment to match Andrew Ng's teaching style.

Issues detected:
{issues}

Original response:
---
{response}
---

Rewrite the response to fix ONLY the listed issues:
- If missing a concrete opening hook: add one (use an everyday scenario, analogy, or "say you have..." opener) BEFORE any definition or technical content.
- If missing a key intuition closing: add an explicit "So the key intuition here is..." or "So what this really means is..." wrap-up at the end.
- If missing numbered structure for a multi-part answer: add "There are N things..." and preserve the same ideas with explicit First/Second/Third structure.
- If missing a comprehension check: add one targeted learning check near the end, not a generic "does that make sense?"
- If generic chatbot filler appears: remove it and replace it with substance.

Keep ALL technical content, source citations, and structure intact. Do NOT shorten the response. Do NOT add "Great question!" or generic filler."""


def preload_resources():
    """
    Preloads all heavy models and indices to minimize runtime query latency.
    Loads the sentence transformer embedding model, BM25 indices, and cross-encoder reranker.
    """
    _get_embedding_function()
    _ensure_bm25_loaded()
    _get_cross_encoder()


# ================================================================================
# Dynamic Memory Extraction LLM Agent
# ================================================================================

MEMORY_UPDATER_PROMPT = """\
You are a highly analytical assistant training a Digital Twin to emulate Andrew Ng.
Your task is to analyze a single conversation turn between a student and Andrew, and extract critical facts, query styles, and personal rapport details to update the student's dynamic profile.

Analyze:
Latest Student Message: {USER_QUERY}
Andrew's Response: {AGENT_RESPONSE}

Current Stored Profile:
{CURRENT_PROFILE}

Your output must be a clean, valid JSON block specifying ONLY changes or additions to apply to the current profile. If there are no updates for a section, omit that key or return an empty dictionary. Do not invent details; only extract concrete details stated or heavily implied by the user's querying style.

JSON Format:
{{
  "student_profile": {{
    "identity": "Extract professional role (e.g., Undergraduate Student, Product Manager, Founder, Researcher) if mentioned",
    "industry_domain": "Extract industry domain (e.g., Healthcare, FinTech, Agriculture) if mentioned",
    "mathematical_comfort_level": "Assess based on query style: 'High (Rigorous)' if they ask about equations, derivatives, gradient derivations; 'Conceptual (Low Math)' if they request high-level intuition or visual explanations; or 'Medium'."
  }},
  "career_and_business_goals": {{
    "short_term": "Extract short-term goals mentioned (e.g., building a spam classifier, passing an exam)",
    "long_term": "Extract long-term ambitions mentioned (e.g., starting an AI product team)"
  }},
  "misconceptions_and_focus_areas": [
    "Identify if the student is confused about specific ML concepts (e.g., 'confuses L1/L2 regularization', 'struggles with bias-variance tradeoff')"
  ],
  "learning_preferences": {{
    "explanation_style": "e.g., 'Heavily analogy-driven' if they praised the Lego brick/fog analogies, 'Code-first', or 'Math-heavy'"
  }},
  "personal_rapport": {{
    "name": "Extract their name if disclosed",
    "location": "Extract location if disclosed",
    "notable_remarks": [
      "Any other unique personal or project context they shared (e.g., 'Deploying an SQLite-backed RAG database')"
    ]
  }},
  "new_topic_discussed": "Single main topic keyword discussed this turn (e.g., Linear Regression, Regularization, Overfitting) to log to timeline",
  "episodic_memories": [
    {{
      "memory": "A compact, reusable fact from this conversation that would help Andrew personalize a future answer",
      "topic": "Short topic label",
      "memory_type": "one of: project_context, learning_preference, misconception, goal, personal_context, domain_interest",
      "tags": ["3-6 lowercase keywords"],
      "importance": "1 for normal, 2 for useful, 3 for highly reusable"
    }}
  ]
}}

Return ONLY valid, raw JSON. Do not include markdown code block formatting (no ```json)."""


def update_user_profile_dynamically(query: str, response: str, current_profile: dict):
    """Invokes a background LLM call to extract student features and merges them into user_profile.json."""
    if not has_gemini_api_key():
        return

    current_profile_str = json.dumps(current_profile, indent=2)
    updater_prompt = MEMORY_UPDATER_PROMPT.format(
        USER_QUERY=query,
        AGENT_RESPONSE=response,
        CURRENT_PROFILE=current_profile_str,
    )

    try:
        res = gemini_generate_content(
            model_name=LLM_MODEL_NAME,
            contents=updater_prompt,
        )
        text = res.text.strip()

        # Clean potential markdown wrapping
        if text.startswith("```json"):
            text = text.replace("```json", "", 1)
        if text.startswith("```"):
            text = text.replace("```", "", 1)
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        updates = json.loads(text)
    except Exception:
        # If extraction fails or times out, safely abort to avoid breaking UI flow
        return

    # Load the latest profile from disk to avoid race conditions with other sessions
    current_profile = load_user_profile()
    modified = False

    # 1. Student Profile
    sp = updates.get("student_profile", {})
    for k, v in sp.items():
        if v and v != "unknown" and current_profile["student_profile"].get(k) != v:
            current_profile["student_profile"][k] = v
            modified = True

    # 2. Career and Business Goals
    goals = updates.get("career_and_business_goals", {})
    for k, v in goals.items():
        if v and v != "unknown" and current_profile["career_and_business_goals"].get(k) != v:
            current_profile["career_and_business_goals"][k] = v
            modified = True

    # 3. Learning Preferences
    pref = updates.get("learning_preferences", {})
    for k, v in pref.items():
        if v and v != "unknown" and current_profile["learning_preferences"].get(k) != v:
            current_profile["learning_preferences"][k] = v
            modified = True

    # 4. Personal Rapport
    rapport = updates.get("personal_rapport", {})
    for k, v in rapport.items():
        if k == "notable_remarks":
            for remark in v:
                if remark and remark not in current_profile["personal_rapport"]["notable_remarks"]:
                    current_profile["personal_rapport"]["notable_remarks"].append(remark)
                    modified = True
        else:
            if v and v != "unknown" and current_profile["personal_rapport"].get(k) != v:
                current_profile["personal_rapport"][k] = v
                modified = True

    # 5. Misconceptions
    for mis in updates.get("misconceptions_and_focus_areas", []):
        if mis and mis not in current_profile["misconceptions_and_focus_areas"]:
            current_profile["misconceptions_and_focus_areas"].append(mis)
            modified = True

    # 6. Timeline discussed
    new_topic = updates.get("new_topic_discussed")
    if new_topic and new_topic != "unknown":
        timeline = current_profile.get("topics_discussed_timeline", [])

        # Check if topic already discussed recently
        exists = any(
            t.get("topic", "").lower() == new_topic.lower() for t in timeline[-3:]
        )
        if not exists:
            import datetime

            today = datetime.date.today().isoformat()
            session_num = (
                1
                if not timeline
                else (
                    timeline[-1].get("session", 1)
                    + (1 if len(timeline) % 5 == 0 else 0)
                )
            )
            timeline.append({
                "topic": new_topic,
                "date": today,
                "session": session_num,
            })
            current_profile["topics_discussed_timeline"] = timeline
            modified = True

    # 7. Cross-session episodic memories
    episodic_store = load_episodic_memory_store()
    entries = episodic_store.get("entries", [])
    episodic_modified = False
    topic_for_memory = new_topic if new_topic and new_topic != "unknown" else "General"

    for item in updates.get("episodic_memories", []):
        if not isinstance(item, dict):
            continue

        memory_text = " ".join(str(item.get("memory", "")).split())
        if not memory_text:
            continue

        topic = " ".join(str(item.get("topic", topic_for_memory)).split()) or topic_for_memory
        memory_type = str(item.get("memory_type", "project_context")).strip() or "project_context"
        tags = _dedupe_memory_list([
            str(tag).strip().lower()
            for tag in item.get("tags", [])
            if str(tag).strip()
        ], limit=6)

        try:
            importance = int(item.get("importance", 1))
        except Exception:
            importance = 1
        importance = max(1, min(importance, 3))

        duplicate_exists = any(
            existing.get("memory", "").strip().lower() == memory_text.lower()
            for existing in entries
        )
        if duplicate_exists:
            continue

        entries.append({
            "memory": memory_text,
            "topic": topic,
            "memory_type": memory_type,
            "tags": tags,
            "importance": importance,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source_query": query[:300],
        })
        episodic_modified = True

    if episodic_modified:
        entries.sort(
            key=lambda entry: (
                entry.get("importance", 1),
                entry.get("timestamp", ""),
            ),
            reverse=True,
        )
        episodic_store["entries"] = entries[:EPISODIC_MEMORY_LIMIT]
        save_episodic_memory_store(episodic_store)

    if modified:
        save_user_profile(current_profile)
