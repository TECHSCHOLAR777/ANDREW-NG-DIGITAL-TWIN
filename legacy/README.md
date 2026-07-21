# Legacy: version one

Superseded code, kept for reference rather than use. Nothing here is imported
by the running system, and none of it is installed by `requirements.txt`.

| File | What it was | What replaced it |
|---|---|---|
| `app.py` | Streamlit interface | `frontend/` (Next.js) plus `backend/app/` (FastAPI) |
| `persona_engine.py` | Prompt playground, 1302 lines | `backend/app/services/persona.py` and `prompt_cache.py` |
| `query_rag.py` | CLI for Chroma plus BM25 search | `backend/app/services/retrieval.py`, hybrid RRF in Postgres |
| `ingest_data.py` | Chroma ingestion | `scripts/ingest_supabase.py` with `scripts/chunking.py` |

## Why it was moved rather than deleted

Version one stored RAG context in local Chroma files and user memory in
`user_profile.json` and `episodic_memory.json`. Version two moved all of it
into one PostgreSQL database with pgvector and full-text search.

`persona_engine.py` was the single largest file in the repository, which meant
it was often the first thing anyone opened, and it described an architecture
the project no longer had. Moving it here removes that confusion while keeping
the migration legible.

Git history preserves everything regardless, so this directory could be deleted
outright without losing anything. It is kept because the before-and-after is
worth being able to point at.
