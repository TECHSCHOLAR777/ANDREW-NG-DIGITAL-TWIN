# Andrew Ng Digital Twin

This is a web application that acts as an interactive digital twin of Andrew Ng. It teaches machine learning concepts using CS229 lecture notes, DeepLearning.ai materials, and transcripts. 

Instead of building a simple RAG chatbot, I wanted a system that builds a dynamic memory graph of the student as we talk. It tracks what you know, what you struggle with, and uses this context to tailor its explanations.

---

## What the Project Does

When you chat with the twin:
1.  **Search:** It searches a database of lecture materials using a custom Postgres function. This combines vector similarity and raw keyword matches.
2.  **Memory:** It retrieves nodes and relationships from a personal memory graph in the database to see your active learning state.
3.  **Generate:** It compiles this data into a system prompt for Gemini, forcing the AI to use Andrew's actual pedagogical traits (using physical props, teaching examples before giving formulas, and keeping a concise, optimistic tone).
4.  **Extract:** In the background, it extracts new facts from the conversation (like "Student struggles with gradient descent") and saves them back to the database graph.

---

## Features

*   **Pedagogical Persona:** Strict prompts enforce Andrew's voice. The AI leads with analogies, keeps responses under 150 words, and matches explanation depth to the student's background.
*   **Postgres-only RAG:** Replaces Chroma and external keyword tools with a single Supabase PostgreSQL instance. It runs semantic vector search (using pgvector) and full-text searches concurrently.
*   **Reciprocal Rank Fusion (RRF):** Merges the semantic and keyword search ranks, applying a prior multiplier to prioritize lecture notes over newsletters or raw transcripts.
*   **Recursive Graph Traversal:** Uses a recursive 2-hop database query to pull active memory nodes and edges, applying graph weight decay as distance increases.
*   **Background Triplet Extraction:** Spawns non-blocking async tasks in FastAPI to parse dialogue, extract relation triplets, and upsert them using trigram fuzzy matching to avoid duplicate concepts (like resolving "backprop" to "Backpropagation").
*   **Offloaded Embeddings:** Offloads embedding generation to Hugging Face Serverless Inference API, keeping RAM usage under 100MB to run within Render's 512MB free tier.

---

## Directory Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI server entrypoint (lifespan hook, DB pool setup)
│   │   ├── routers/
│   │   │   └── chat.py          # /message, /graph, and /clear endpoints
│   │   └── services/
│   │       ├── prompt_cache.py  # Prompt compiler & context assembly
│   │       └── triplet_extractor.py # Background SPO triplet extraction
│   └── migrations/
│       ├── 001_knowledge_graph_schema.sql  # Entities, relationships, and chunks tables
│       ├── 002_entity_resolution_and_traversal.sql # 2-hop CTE query & entity resolution function
│       ├── 003_hybrid_retrieval_rrf.sql     # RRF hybrid search stored procedure
│       └── 004_production_hardening.sql    # Index optimizations
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx         # Chat UI and memory matrix dashboard
│   │   │   └── layout.tsx
│   │   └── components/          # Interactive memory matrix graph view
│   ├── package.json
│   └── tsconfig.json
├── scripts/
│   ├── ingest_supabase.py       # Python script to seed database chunks & embeddings
│   ├── app.py                   # Legacy Streamlit app
│   └── collect_*.py             # Source scraper scripts
├── architecture.md              # Deep dive architectural documentation
├── requirements.txt             # Python dependencies
└── Dockerfile                   # Deployment file
```

---

## Configuration

You need to set up two environment variables in a `.env` file in the root directory:

```env
DATABASE_URL=postgresql+asyncpg://postgres:your_password@db.your_supabase_project.supabase.co:5432/postgres
GEMINI_API_KEY=your_gemini_api_key_here
HF_TOKEN=your_hugging_face_token_here (Optional: for higher rate limits on embeddings)
```

### Database Setup
Execute the migration scripts in the following order against your PostgreSQL instance to create the tables, indexes, and stored procedures:

1.  `backend/migrations/001_knowledge_graph_schema.sql`
2.  `backend/migrations/002_entity_resolution_and_traversal.sql`
3.  `backend/migrations/003_hybrid_retrieval_rrf.sql`
4.  `backend/migrations/004_production_hardening.sql`

---

## Installation & Setup

### 1. Backend Setup
1.  Install the Python requirements:
    ```bash
    pip install -r requirements.txt
    ```
2.  Seed the database with the grounding materials:
    ```bash
    python scripts/ingest_supabase.py
    ```
3.  Start the FastAPI application:
    ```bash
    python -m uvicorn backend.app.main:app --reload
    ```
    The server will startup and run on `http://127.0.0.1:8000`.

### 2. Frontend Setup
1.  Navigate to the frontend folder:
    ```bash
    cd frontend
    ```
2.  Install packages and run the development server:
    ```bash
    npm install
    npm run dev
    ```
3.  Open the web interface in your browser at `http://localhost:3000`.

---

## Usage & Verification

To verify that the digital twin is working correctly, send these queries in the chat:

*   **The Prop Analogy:** Ask, *"Explain Neural Networks."* The response must lead with an analogy using Lego bricks.
*   **The Anchor Example:** Ask, *"Explain Linear Regression."* The response must use housing price predictions as the anchor example.
*   **Career Advice:** Ask, *"How can I build a career in AI?"* The agent should give you concrete steps, acknowledge your professional background, and emphasize building projects over just reading textbooks.

### Resetting Memory
The frontend generates a fresh UUID for the session on every page mount to isolate your database memory. If you want to wipe the current state, click the "Reset learning memory" button. This cascade-deletes all turns, nodes, and edges associated with the current UUID, and issues a fresh session identifier.
