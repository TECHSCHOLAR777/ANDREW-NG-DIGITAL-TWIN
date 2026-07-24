# Andrew Ng Digital Twin 🎓🤖

An interactive, AI-powered digital twin of Professor Andrew Ng — a grounded, unofficial recreation of his public knowledge, reasoning, and voice. It is built for researchers, engineers, founders, product and business leaders, students, and the curious; teaching ML is one of its behaviours, not its whole purpose. Rather than a standard, stateless RAG chatbot, this system implements a dynamic contextual-memory knowledge graph that tracks the context you share, matches depth to your background (PhD vs. beginner, founder vs. researcher), and remembers you across chat sessions.

---

## 🏗️ Architecture & How It Works

When you interact with the digital twin:
1. **Client Headers & BYOK:** The frontend communicates with the FastAPI backend using standard UUID-based multi-tenancy (`X-Tenant-Id`) and an optional client-supplied key (`X-Gemini-Api-Key`). These are persisted in browser local storage.
2. **Hybrid RAG Retrieval:** The backend embeds user queries with the configured embedding provider (default **Jina `jina-embeddings-v3`, 1024-dimensional vectors** — see migration 014; a local `all-mpnet-base-v2` SentenceTransformer remains an option for offline/dev). Query and corpus vectors share the same space. It runs a PostgreSQL function combining vector cosine similarity (via `pgvector`) and Full-Text Search (FTS) using **Reciprocal Rank Fusion (RRF)**.
3. **Dual-Scope Memory:**
   - **Cross-Session Recall:** A recursive 2-hop CTE database query retrieves the student's global learning state across all chat history associated with the `X-Tenant-Id`.
   - **Session-Scoped Visual Graph:** The interactive graph displays only the triplets discovered or updated in the current active chat session.
4. **Context Caching:** The static persona is placed first so current Gemini models can apply implicit prefix caching. Retrieved corpus passages stay fresh for every turn instead of being frozen into a stale session cache.
5. **Background Triplet Extraction:** After sending a response, FastAPI spawns a non-blocking background task. A specialized Gemini call parses the turn to extract subject-predicate-object (SPO) triplets (e.g. `(Student, struggles_with, Gradient Descent)`).
6. **Entity Resolution:** The backend runs trigram fuzzy matching to resolve synonyms or abbreviations (e.g., merging "backprop" into "Backpropagation") before persisting nodes.
7. **Voice Interaction:** The system supports hands-free audio. The UI uses the browser's Web Speech API for voice-to-text, and synthesizes audio via either a local cloned-voice server (Chatterbox on port 5002) or native browser text-to-speech.

---

## 📂 Directory Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI server entrypoint (lifespan hook, DB pool, model preloading)
│   │   ├── routers/
│   │   │   └── chat.py          # /message, /graph/{session_id}, /clear, and /tts endpoints
│   │   └── services/
│   │       ├── prompt_cache.py  # Prompt compiler, context assembly, and Gemini context caching
│   │       └── triplet_extractor.py # Background SPO triplet extraction and entity resolution
│   └── migrations/
│       ├── 001_knowledge_graph_schema.sql  # Base entities, relationships, and grounding chunks tables
│       ├── 002_entity_resolution_and_traversal.sql # 2-hop CTE query & fuzzy resolution database function
│       ├── 003_hybrid_retrieval_rrf.sql     # RRF hybrid search stored procedure
│       ├── 004_production_hardening.sql     # Database indexes (trigram, GIN, vector index)
│       └── 005_session_scoped_relations.sql # [NEW] Graph session isolation columns & updated traversal functions
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx         # Responsive Chat UI, voice handlers, and memory controls
│   │   │   ├── layout.tsx       # Root layout configuration
│   │   │   └── globals.css      # Core Tailwind CSS v4 directives
│   │   ├── components/
│   │   │   └── KnowledgeGraphView.tsx # Interactive graph rendering with React Flow & D3-force layout
│   │   ├── lib/
│   │   │   └── graphMapper.ts   # Maps DB tables to React Flow nodes/edges with predicate coloring
│   │   └── types/
│   │       └── graph.ts         # TypeScript schema definitions for graph nodes and relations
│   ├── package.json             # Next.js 16, React 19, @xyflow/react (React Flow 12), and Tailwind CSS v4
│   └── tsconfig.json
├── scripts/
│   ├── ingest_supabase.py       # Seeds the Supabase database with grounded materials and local embeddings
│   ├── clean_text.py            # Text corpus normalizer
│   ├── collect_*.py             # Raw data scrapers (blog posts, PDFs, transcripts, etc.)
│   ├── generate_conversations.py# Context generator script
│   ├── chunking.py              # Structure-aware chunking (headings, overlap)
│   ├── build_curriculum.py      # Offline prerequisite DAG extraction
│   ├── migrate.py               # Applies migrations in order, records them
│   └── eval/                    # Retrieval, persona and memory evaluation
├── legacy/                      # Superseded version one, kept for reference
├── run_chatterbox_server.py     # Local TTS clone server runner
├── architecture.md              # Deep dive system design details
├── requirements.txt             # Python dependencies
└── Dockerfile                   # Deployment container
```

---

## Setup status

Run this first. It checks every layer and names exactly what is missing:

```bash
python scripts/smoke_test.py
```

**No local GPU?** The cloned voice runs on a free Kaggle T4 via
[notebooks/kaggle_tts_server.ipynb](notebooks/kaggle_tts_server.ipynb). Without
it, voice falls back to browser speech synthesis automatically.

**Guides**

| Guide | Covers |
|---|---|
| [docs/NEON_SETUP.md](docs/NEON_SETUP.md) | Database setup and full deployment |
| [docs/VOICE_SETUP.md](docs/VOICE_SETUP.md) | Cloned voice on a Kaggle GPU, and voice mode |
| [scripts/eval/README.md](scripts/eval/README.md) | Retrieval, persona and memory evaluation |
| [docs/PRIVACY.md](docs/PRIVACY.md) | What is stored and where it goes |
| [docs/POSTURE.md](docs/POSTURE.md) | Affiliation, corpus rights, voice cloning policy |

---

## ⚙️ Configuration & Environment Variables

Create a `.env` file in the root directory:

```env
DATABASE_URL=postgresql+asyncpg://postgres:your_supabase_password@db.your_supabase_project.supabase.co:5432/postgres
GEMINI_API_KEY=your_gemini_api_key_here
CORPUS_TENANT_ID=optional_uuid_that_owns_the_shared_andrew_corpus
MAX_TTS_CHARS=1200
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
ENVIRONMENT=development

# Text-to-speech service (defaults to the local Chatterbox server)
CHATTERBOX_URL=http://127.0.0.1:5002/v1/audio/speech

# Retrieval tuning (all optional, shown with their defaults)
EMBED_PROVIDER=jina
JINA_API_KEY=                    # required by the default provider
JINA_EMBED_MODEL=jina-embeddings-v3
EMBED_DIMS=1024
EMBED_MODEL=all-mpnet-base-v2    # used only with EMBED_PROVIDER=local
EMBED_WORKERS=2
RETRIEVAL_NEIGHBOR_WINDOW=1      # chunks pulled either side of each hit
RETRIEVAL_RRF_K=60
RETRIEVAL_VECTOR_WEIGHT=0.65
RETRIEVAL_FTS_WEIGHT=0.35
RETRIEVAL_MIN_COSINE=0.35        # below this the answer is flagged ungrounded
ENABLE_QUERY_REWRITE=true        # rewrite follow-ups into standalone questions
GEMINI_MODEL=gemini-3.6-flash    # main conversational model
GEMINI_UTILITY_MODEL=gemini-3.5-flash-lite
MAX_CACHE_MANAGERS=128           # bound on cached per-key prompt managers
```

> [!WARNING]
> `ENVIRONMENT=production` enforces true BYOK: the server-side `GEMINI_API_KEY`
> fallback is disabled and every request must carry the user's own key. Leaving
> this at `development` on a public deployment means anonymous visitors bill your key.

> [!NOTE]
> The backend accepts client-provided keys sent via the `X-Gemini-Api-Key` header. If missing, it falls back to the backend's `.env` key.
> `CORPUS_TENANT_ID` is optional. If omitted, retrieval treats `knowledge_chunks` as a shared corpus and searches all ingested chunks while keeping user memory tenant-scoped.

### Database Migrations
The ordered SQL files in `backend/migrations/` are the database history. Run
`python scripts/migrate.py`; it applies only outstanding files in order, records
their checksums in `schema_migrations`, and supports `--status` and `--dry-run`.
Do not edit a migration after it has been applied—add the next numbered file.

> [!IMPORTANT]
> Migration 008 replaces the IVFFlat vector indexes with HNSW. The originals were
> created before any data was ingested, so their centroids were trained on an empty
> table and recall was silently degraded. Run it after your corpus is ingested.

---

## Curriculum graph

Every concept in the memory graph comes from conversation, which means it only
ever knows things a student has already mentioned. The curriculum layer adds
the other half: a prerequisite DAG over machine learning concepts, extracted
once from the corpus rather than from any user.

The student graph then becomes an overlay on it. The curriculum says what
depends on what; the student layer says where this person is. Three things
become computable that a prompt cannot do:

- **Learning paths.** Given a target concept, a topological sort over the
  prerequisites the student has not yet mastered. The same target yields a
  short path for an advanced learner and a long one for a beginner.
- **Root cause diagnosis.** When several separate confusions share one upstream
  prerequisite, that prerequisite is the real problem. A student stuck on
  backpropagation, gradient descent and Adam does not have three problems.
- **Pedagogical retrieval.** If the question depends on a concept the student
  is shaky on, material for that concept is retrieved too, even though the
  question never mentioned it.

```bash
# One-time build. A few hundred model calls over the structured documents.
python scripts/build_curriculum.py --out data/baselines/curriculum.json

# Review the JSON, correct anything wrong, then load it.
python scripts/build_curriculum.py --load data/baselines/curriculum.json
```

The output is a reviewable, versioned artifact rather than an opaque table, so
a bad extraction is a diff. Everything degrades gracefully when no curriculum
is loaded: the product behaves exactly as it did before, without prerequisite
reasoning.

---

## Evaluation

The project measures itself in three layers. Details in
[`scripts/eval/README.md`](scripts/eval/README.md).

```bash
# Unit tests: chunking, sanitisation, routing, persona validators. No API key.
for f in backend/tests/test_*.py; do python "$f"; done

# Style baseline measured from the real corpus. Offline, about a minute.
python scripts/eval/corpus_style.py --save data/baselines/corpus_style.json

# Persona: rule violations plus distance from that measured style.
python scripts/eval/persona_eval.py

# Retrieval: recall@k, MRR, abstention calibration, feature ablations.
python scripts/eval/golden_set.py --n 100 --negatives 20
python scripts/eval/retrieval_eval.py --ablate

# Memory: scripted multi-session scenarios asserting what the graph believes.
python scripts/eval/memory_eval.py
```

CI runs the offline subset plus a job that applies every migration in order
against pgvector, so ordering and syntax errors are caught before Supabase.

---

## 🚀 Installation & Setup

### 1. Backend Setup
1. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
2. Ingest grounding materials:
   ```bash
   python scripts/ingest_supabase.py
   ```
   *This loads files under `data/cleaned/`, computes embeddings with the configured provider (default Jina, 1024-dim — set `EMBED_PROVIDER` and the matching key in `.env`), and writes them to your database. Query-time and ingest-time embeddings must use the same provider so the vectors share one space.*
3. Run the FastAPI backend:
   ```bash
   python -m uvicorn backend.app.main:app --reload
   ```
   *The server runs on `http://127.0.0.1:8000`. With the default Jina provider it calls the Jina API for embeddings; with `EMBED_PROVIDER=local` it preloads `all-mpnet-base-v2` on startup instead.*

### 2. Cloned-Voice TTS (Optional)
To enable high-fidelity voice cloning rather than generic browser TTS:
1. Install voice requirements:
   ```bash
   pip install chatterbox-tts torchaudio soundfile
   ```
2. Place your reference audio file named `andrew_ng_ref.wav` into `backend/data/`.
3. Start the local speech server:
   ```bash
   python run_chatterbox_server.py
   ```
   *The TTS service listens on port `5002`. The backend will automatically direct `/tts` requests to it.*

### 3. Frontend Setup
1. Navigate to the folder:
   ```bash
   cd frontend
   ```
2. Install packages and start the Next.js server:
   ```bash
   # Optional: point the UI at a non-local backend
   # NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
   npm install
   npm run dev
   ```
3. Open `http://localhost:3000` in your browser.

---

## 🧪 E2E Verification Walkthrough

To verify that the system is functioning correctly, go through this multi-session pipeline:

### Session 1: Concept Explanations & Persona Calibration
1. **Clean Slate:** Click **Reset learning memory** to ensure a blank graph.
2. **Greeting:** Type: *"Hi, I'm Michael and I'm a product manager at a retail firm. I want to build a customer support routing system."*
   - *Check:* Response must be written in the first person, engage the topic immediately (no *"Great question!"* or boilerplate openers), and ask for input/output definitions.
   - *Graph (after 12s, hit Sync):* The graph displays a Student node labeled **Michael** with edges connecting to **Product Manager** and **Retail**.
3. **Analogy Check:** Ask: *"Can you explain what gradient descent is?"*
   - *Check:* The response must use the **walking downhill in thick fog** analogy, follow a example-first format, and avoid bullet-point lists or markdown headers.

### Session 2: Target Calibration (Researcher Mode)
1. **New Session:** Click **New Chat** (this isolates the active graph session but preserves global memory).
2. **Introduce Priya:** Type: *"I'm Priya, a PhD student working on attention. Can you explain self-attention?"*
   - *Check:* The backend detects a technical student and skips hand-holding, using advanced terms like Query/Key/Value matrices directly.
   - *Graph:* Toggling **Session View** shows only Priya's attention graph. Toggling **Global View** shows both Michael's retail-routing graph and Priya's attention graph.

### Session 3: Cross-Session Recall
1. **New Session:** Click **New Chat**.
2. **Query:** Type: *"Hi, I'm Michael again. What were we discussing earlier?"*
   - *Check:* The backend queries the global tenant memory and recalls Michael's retail-routing project and gradient descent discussion from Session 1.
