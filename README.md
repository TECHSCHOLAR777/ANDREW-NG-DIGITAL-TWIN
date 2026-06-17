# Andrew Ng Digital Twin 🎓🤖

An interactive, AI-powered digital twin of Professor Andrew Ng designed to teach machine learning concepts. Rather than a standard, stateless RAG chatbot, this system implements a dynamic student-personality knowledge graph that tracks your comprehension, matches explanations to your background (PhD vs. Beginner), and remembers you across chat sessions.

---

## 🏗️ Architecture & How It Works

When you interact with the digital twin:
1. **Client Headers & BYOK:** The frontend communicates with the FastAPI backend using standard UUID-based multi-tenancy (`X-Tenant-Id`) and an optional client-supplied key (`X-Gemini-Api-Key`). These are persisted in browser local storage.
2. **Hybrid RAG Retrieval:** The backend embeds user queries using a preloaded local **SentenceTransformer (`all-mpnet-base-v2`)** model producing **768-dimensional vectors**. It runs a Supabase PostgreSQL function combining vector cosine similarity (via `pgvector`) and Full-Text Search (FTS) using **Reciprocal Rank Fusion (RRF)**.
3. **Dual-Scope Memory:**
   - **Cross-Session Recall:** A recursive 2-hop CTE database query retrieves the student's global learning state across all chat history associated with the `X-Tenant-Id`.
   - **Session-Scoped Visual Graph:** The interactive graph displays only the triplets discovered or updated in the current active chat session.
4. **Context Caching:** It utilizes Gemini's context caching API (`CachedContent`) to cache the static corpus chunks and Andrew's massive persona instructions, reducing API costs and latency.
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
│   ├── app.py                   # Legacy Streamlit interface
│   ├── clean_text.py            # Text corpus normalizer
│   ├── collect_*.py             # Raw data scrapers (blog posts, PDFs, transcripts, etc.)
│   ├── generate_conversations.py# Context generator script
│   ├── persona_engine.py        # System prompt playground
│   └── query_rag.py             # CLI playground for hybrid search testing
├── run_chatterbox_server.py     # Local TTS clone server runner
├── architecture.md              # Deep dive system design details
├── requirements.txt             # Python dependencies
└── Dockerfile                   # Deployment container
```

---

## ⚙️ Configuration & Environment Variables

Create a `.env` file in the root directory:

```env
DATABASE_URL=postgresql+asyncpg://postgres:your_supabase_password@db.your_supabase_project.supabase.co:5432/postgres
GEMINI_API_KEY=your_gemini_api_key_here
ENVIRONMENT=development
```

> [!NOTE]
> The backend accepts client-provided keys sent via the `X-Gemini-Api-Key` header. If missing, it falls back to the backend's `.env` key.

### Database Migrations
Run these scripts sequentially in your Supabase SQL editor or direct database interface:
1. `backend/migrations/001_knowledge_graph_schema.sql`
2. `backend/migrations/002_entity_resolution_and_traversal.sql`
3. `backend/migrations/003_hybrid_retrieval_rrf.sql`
4. `backend/migrations/004_production_hardening.sql`
5. `backend/migrations/005_session_scoped_relations.sql`

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
   *This loads files under `data/cleaned/`, computes 768-dim embeddings locally via SentenceTransformers, and writes them to your database.*
3. Run the FastAPI backend:
   ```bash
   python -m uvicorn backend.app.main:app --reload
   ```
   *The server preloads the `all-mpnet-base-v2` model on startup and runs on `http://127.0.0.1:8000`.*

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
