<div align="center">

<h1>Andrew Ng Digital Twin</h1>

<h3>An unofficial, source-grounded conversational recreation of Andrew Ng's public teaching and writing</h3>

<p>It combines hybrid retrieval, persistent contextual memory, an inspectable knowledge graph, and optional synthetic speech in one web application.</p>

<p>
  <a href="https://digital-twin-kohl-six.vercel.app/">
    <img src="https://img.shields.io/badge/Live_demo-Open_the_twin-ff6b1a?style=for-the-badge" alt="Open the live demo">
  </a>
  <a href="https://github.com/TECHSCHOLAR777/DIGITAL-TWIN/actions/workflows/tests.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/TECHSCHOLAR777/DIGITAL-TWIN/tests.yml?branch=master&style=for-the-badge&label=Build" alt="Build status">
  </a>
</p>

<p>
  <img src="https://img.shields.io/badge/Next.js-16-111111?logo=nextdotjs" alt="Next.js 16">
  <img src="https://img.shields.io/badge/React-19-20232a?logo=react" alt="React 19">
  <img src="https://img.shields.io/badge/FastAPI-2.0_API-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169e1?logo=postgresql" alt="PostgreSQL with pgvector">
  <img src="https://img.shields.io/badge/Gemini-BYOK-8e75b2?logo=googlegemini" alt="Gemini bring your own key">
</p>

<p>
  <a href="https://digital-twin-kohl-six.vercel.app/">Live application</a>
  &nbsp;&middot;&nbsp;
  <a href="https://digital-twin-kohl-six.vercel.app/understand">How it works</a>
  &nbsp;&middot;&nbsp;
  <a href="#privacy-and-data-boundaries">Privacy</a>
  &nbsp;&middot;&nbsp;
  <a href="#responsible-use">Responsible use</a>
</p>

<sub>
This project is not affiliated with, endorsed by, or reviewed by Andrew Ng, Stanford University, or DeepLearning.AI. Responses are generated and are not real quotations. Any cloned voice is synthetic.
</sub>

</div>

<br>

<p align="center">
  <a href="https://digital-twin-kohl-six.vercel.app/">
    <img src="docs/assets/landing-page.webp" alt="Andrew Ng Digital Twin production landing page" width="100%">
  </a>
</p>

## What this project is

Andrew Ng Digital Twin is a full-stack conversational system built around Andrew Ng's publicly available educational material. The current corpus contains 529 cleaned source documents and about 1.7 million words from lectures, course notes, books, newsletters, interviews, and public writing.

The application retrieves relevant passages before answering, adjusts the depth and framing to the person asking, and carries useful context across sessions. It can answer in streamed text, expose the passages and memory graph behind a response, or run as a hands-free voice conversation.

This is an engineering and research project, not a claim to reproduce a real person. The system identifies itself as an unofficial recreation, keeps the synthetic-voice disclosure visible, and should not be used to attribute new statements to Andrew Ng.

## Product capabilities

| Capability | What it does |
|---|---|
| Grounded conversation | Searches Andrew Ng's public corpus with semantic and keyword retrieval before generating a response. |
| Adaptive explanations | Changes notation, depth, pacing, and examples for researchers, engineers, founders, product leaders, and learners. |
| Contextual memory | Extracts useful facts and relationships from conversations into a tenant-scoped, time-aware graph. |
| Persistent sessions | Stores chat sessions and restores them after sign-in. Account passwords are stored as bcrypt hashes and Auth.js uses JWT sessions. |
| Inspectable evidence | Shows retrieved passages, grounding state, and a session or global view of the memory graph. |
| Streamed responses | Sends progress events and generated tokens over Server-Sent Events so the interface remains responsive during retrieval and generation. |
| Interactive voice | Uses browser speech recognition for input and sentence-level speech playback for low perceived latency. |
| Voice fallback | Uses the Chatterbox clone when its GPU service is reachable and switches to a pinned browser voice when it is not. |
| Bring your own key | Accepts a Gemini API key from each user. Production disables the server-side fallback key. |
| User-controlled deletion | Supports individual session deletion, graph-edge correction, and a full reset of tenant-scoped chat and memory data. |

## System architecture

```mermaid
flowchart LR
    Browser["Browser<br/>Next.js 16 and React 19"]
    API["FastAPI API<br/>routing, orchestration, rate limits"]
    Retrieval["Hybrid retrieval<br/>pgvector + PostgreSQL FTS + RRF"]
    Memory["Context memory<br/>temporal graph + curriculum"]
    Database[("PostgreSQL<br/>pgvector")]
    Gemini["Gemini models<br/>user-provided key"]
    TTS["TTS broker"]
    Clone["Chatterbox clone<br/>optional Kaggle GPU"]
    Fallback["Browser speech<br/>fallback"]
    Speech["Browser speech<br/>recognition"]

    Browser -->|"SSE chat and REST"| API
    API --> Retrieval
    API --> Memory
    Retrieval --> Database
    Memory --> Database
    API --> Gemini
    Gemini -->|"streamed tokens"| API
    API -->|"SSE events"| Browser
    Browser --> Speech
    API --> TTS
    TTS --> Clone
    Clone --> Browser
    Browser -. "when clone is unavailable" .-> Fallback
    Fallback --> Browser
```

The deployed system uses Vercel for the frontend, Render for the FastAPI service, Neon for PostgreSQL and pgvector, and an optional Kaggle GPU notebook for cloned speech.

## What happens during a turn

```mermaid
sequenceDiagram
    participant UI as Next.js client
    participant API as FastAPI
    participant DB as PostgreSQL + pgvector
    participant LLM as Gemini
    participant Voice as TTS service

    UI->>API: POST /api/v1/chat/stream
    API->>DB: Load session, learner state, and graph context
    API->>DB: Hybrid vector and full-text retrieval
    DB-->>API: Ranked passages and relevant memory
    API->>LLM: Persona, evidence, memory, and user question
    LLM-->>API: Generated response stream
    API-->>UI: Progress, token, citation, and completion events
    opt Interactive voice
        UI->>API: Sentence-level TTS request
        API->>Voice: Synthesize one sentence
        Voice-->>UI: Audio or unavailable status
        UI-->>UI: Use browser speech when unavailable
    end
    API-->>LLM: Extract memory facts in the background
    API-->>DB: Resolve entities and update temporal relations
```

The retrieval path combines pgvector cosine similarity with PostgreSQL full-text search using Reciprocal Rank Fusion. Adjacent chunks are added when they preserve definitions or notation that a top result depends on. If the best semantic match is below the configured confidence threshold, the response is marked ungrounded instead of presenting weak evidence as authoritative.

The memory update runs after the answer is sent. Entity aliases are resolved before facts are stored, and later corrections retire old relations instead of leaving contradictory versions active.

## Technology

| Layer | Main components |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Auth.js 5 |
| Conversation UI | Server-Sent Events, React Markdown, KaTeX, browser Web Speech APIs |
| Graph UI | React Flow 12, D3 force layout |
| Backend | Python 3.11, FastAPI, asyncpg, Pydantic, httpx |
| Generation | Gemini generation and utility models through per-request clients |
| Retrieval | Jina embeddings by default, pgvector, PostgreSQL full-text search, RRF |
| Memory | Temporal entity graph, alias resolution, session and tenant isolation |
| Voice | Chatterbox Turbo clone service with browser speech-synthesis fallback |
| Deployment | Vercel, Render, Neon, Kaggle, Cloudflare quick tunnel |

## Repository map

```text
.
|-- backend/
|   |-- app/
|   |   |-- main.py                 FastAPI application and database pool
|   |   |-- routers/chat.py         Chat, stream, history, graph, reset, and TTS routes
|   |   `-- services/               Retrieval, memory, persona, models, and extraction
|   |-- migrations/                 17 ordered PostgreSQL and pgvector migrations
|   `-- tests/                      Offline backend regression tests
|-- frontend/
|   |-- src/app/page.tsx            Public landing page
|   |-- src/app/app/page.tsx        Main conversation workspace
|   |-- src/app/understand/         Product and pipeline explanation
|   |-- src/components/             Chat, graph, auth, voice, and marketing UI
|   `-- public/                      Static assets
|-- scripts/
|   |-- collect_*.py                Public-source collection tools
|   |-- clean_text.py               Corpus normalization
|   |-- ingest_supabase.py          Chunking, embedding, and database ingestion
|   |-- migrate.py                  Ordered, checksummed migration runner
|   |-- smoke_test.py               Dependency and deployment diagnostics
|   `-- eval/                       Retrieval, persona, and memory evaluation
|-- notebooks/
|   `-- kaggle_tts_server.ipynb     Optional GPU voice service
|-- docs/                            Privacy, deployment, voice, and posture guides
|-- legacy/                          Superseded first version, retained for reference
`-- Dockerfile                      Lean backend runtime image
```

## Run it locally

### Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer
- PostgreSQL 16 with the `vector` extension, or a compatible hosted database such as Neon
- A Jina API key for the default embedding provider
- A Gemini API key entered in the application, or a development-only backend fallback key
- Optional: an NVIDIA GPU or Kaggle notebook for the cloned voice

### 1. Clone and install the backend

```bash
git clone https://github.com/TECHSCHOLAR777/DIGITAL-TWIN.git
cd DIGITAL-TWIN

python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS or Linux
source .venv/bin/activate
```

Install the runtime dependencies:

```bash
pip install -r requirements.txt
```

### 2. Configure the backend

Copy `.env.example` to `.env`, then set at least:

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
ENVIRONMENT=development
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

EMBED_PROVIDER=jina
JINA_API_KEY=your_jina_key
EMBED_DIMS=1024

# Optional in development. Leave unset in production.
GEMINI_API_KEY=

# Optional cloned-voice service.
CHATTERBOX_URL=http://127.0.0.1:5002/v1/audio/speech
```

> [!IMPORTANT]
> Corpus ingestion and request-time retrieval must use the same embedding provider, model, and dimensions. Mixing embedding spaces can return plausible but unrelated passages without producing an obvious runtime error.

Apply all outstanding migrations:

```bash
python scripts/migrate.py
python scripts/migrate.py --status
```

The migration runner records checksums in `schema_migrations`. Do not edit a migration after it has been applied. Add the next numbered migration instead.

### 3. Prepare a corpus

The production database is already populated, but the repository does not redistribute the collected source text. To build a database from source material, install the collection dependencies and run the pipeline:

```bash
pip install -r requirements-ingest.txt

python scripts/collect_pdfs.py
python scripts/collect_transcripts.py
python scripts/collect_the_batch.py
python scripts/collect_blog_posts.py
python scripts/clean_text.py
python scripts/ingest_supabase.py
```

Review each source's terms and licensing before collecting or redistributing material. Some collectors may also expect user-supplied files. The ingestion script is resumable and refuses to mix incompatible embedding models.

The optional curriculum graph is built separately:

```bash
python scripts/build_curriculum.py --out data/baselines/curriculum.json
# Review the generated file before loading it.
python scripts/build_curriculum.py --load data/baselines/curriculum.json
```

### 4. Start the API

```bash
python -m uvicorn backend.app.main:app --reload --port 8000
```

Useful local endpoints:

- Health: `http://127.0.0.1:8000/health`
- OpenAPI: `http://127.0.0.1:8000/docs`

API documentation is disabled when `ENVIRONMENT=production`.

### 5. Configure and start the frontend

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
AUTH_SECRET=replace_with_a_long_random_secret
```

The frontend and backend must point to the same database because the Next.js server handles account creation and authentication while FastAPI owns conversation data.

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`.

### Docker Compose

If the database is already available and `.env` is configured:

```bash
docker compose up --build
```

Compose starts the frontend and API. It does not start PostgreSQL or the GPU voice service.

## Configuration reference

The complete list and current defaults live in [`.env.example`](.env.example). These are the variables most operators need:

| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | Backend and frontend | PostgreSQL connection used for domain data and accounts. |
| `ENVIRONMENT` | Backend | Enables development helpers or production BYOK enforcement. |
| `CORS_ALLOW_ORIGINS` | Backend | Comma-separated frontend origins allowed to call the API. |
| `JINA_API_KEY` | Backend and ingestion | Authenticates the default embedding provider. |
| `EMBED_PROVIDER` | Backend and ingestion | Selects `jina`, `voyage`, `gemini`, or `local`. |
| `EMBED_DIMS` | Backend and database | Vector width. The deployed corpus uses 1024 dimensions. |
| `GEMINI_API_KEY` | Backend, development only | Optional fallback for local development and offline tooling. |
| `GEMINI_MODEL` | Backend | Main conversational generation model. |
| `GEMINI_UTILITY_MODEL` | Backend | Default model for query rewriting and graph extraction. |
| `CHATTERBOX_URL` | Backend | OpenAI-compatible endpoint for cloned speech. |
| `CORPUS_TENANT_ID` | Backend and ingestion | Protects the stable shared-corpus tenant from reset operations. |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend | Public FastAPI origin, embedded into the client build. |
| `AUTH_SECRET` | Frontend | Signs Auth.js JWT sessions. |

> [!WARNING]
> Set `ENVIRONMENT=production` on every public backend and do not configure a production `GEMINI_API_KEY`. Production requests must carry the visitor's `X-Gemini-Api-Key` header so one server-owned key cannot be billed by anonymous users.

In the browser, the Gemini key is kept in `sessionStorage`, not persistent local storage. The backend uses it for the active request and does not write it to the database.

## Key API routes

All conversation routes use the `/api/v1/chat` prefix.

| Method and route | Purpose |
|---|---|
| `POST /stream` | Stream progress, answer tokens, grounding data, and completion metadata. |
| `POST /message` | Return a non-streamed response for API clients and tests. |
| `GET /sessions` | List the caller's stored sessions. |
| `GET /sessions/{id}/messages` | Restore a session transcript. |
| `DELETE /sessions/{id}` | Delete one session and its scoped relations. |
| `GET /graph/{session_id}` | Load the session or global memory graph. |
| `DELETE /graph/edge/{edge_id}` | Remove an incorrect relationship. |
| `POST /clear` | Reset tenant-scoped sessions, turns, entities, aliases, and relations. |
| `GET /tts/status` | Report whether the cloned-voice service is currently reachable. |
| `POST /tts` | Proxy one sentence to the cloned-voice service. |
| `GET /curriculum/path` | Build a prerequisite-aware path toward a target concept. |

Conversation calls require:

```http
X-Tenant-Id: <uuid>
X-Gemini-Api-Key: <user key>
```

The tenant header isolates conversation and memory data. Production does not silently replace a missing user key with a server key.

## Voice mode

Voice mode is split into three independent parts:

1. The browser's speech-recognition API turns microphone input into text.
2. The normal chat pipeline streams the answer and emits complete sentences as they become available.
3. Each sentence is synthesized by the Chatterbox service or sent directly to the configured browser voice when the clone is unavailable.

The cloned service is optional because GPU notebook sessions and tunnel URLs are temporary. The UI checks availability before playback, identifies the active provider, and can continue the conversation through browser speech instead of waiting for an unreachable GPU.

To run the clone on Kaggle, use [`notebooks/kaggle_tts_server.ipynb`](notebooks/kaggle_tts_server.ipynb) and follow [the voice setup guide](docs/VOICE_SETUP.md). The notebook prints a new `CHATTERBOX_URL` whenever its tunnel is restarted. The application must keep the synthetic-voice disclosure visible regardless of provider.

## Privacy and data boundaries

- Conversation turns, sessions, account context, and graph memory are stored in PostgreSQL under a tenant UUID.
- Account passwords are stored only as bcrypt hashes.
- The Gemini key is held in browser session storage and sent with generation requests. It is not persisted by the application.
- Microphone audio is handled by the browser speech-recognition provider. The application sends recognized text to its backend.
- The app does not store generated TTS audio as conversation data.
- Session deletion and full reset operations are tenant-scoped.
- Requests to Gemini, the embedding provider, and the optional TTS service leave the application boundary.

Review these boundaries against the policies of every model, embedding, speech-recognition, and hosting provider before operating a public instance.

## Testing and evaluation

The repository separates deterministic checks from evaluations that need a live database or model key.

```bash
# Backend regression tests
for file in backend/tests/test_*.py; do python "$file" || exit 1; done

# Frontend checks
cd frontend
npx tsc --noEmit
npm run lint
npm run build

# Database and service diagnostics
cd ..
python scripts/migrate.py --status
python scripts/smoke_test.py
```

CI runs the offline backend tests, the frontend type and production builds, and all 17 migrations against PostgreSQL 16 with pgvector.

The evaluation suite measures:

- retrieval recall, reciprocal rank, abstention, and feature ablations;
- persona-rule violations and distance from corpus-measured style;
- multi-session memory creation, revision, isolation, and deletion.

See [`scripts/eval/README.md`](scripts/eval/README.md) for commands, required credentials, and interpretation.

## Deployment

The public instance is split across four services:

| Component | Platform | Operational note |
|---|---|---|
| Frontend and authentication | Vercel | `NEXT_PUBLIC_API_BASE_URL` is fixed at build time. |
| FastAPI backend | Render | `/health` is public; free instances can cold start. |
| PostgreSQL and pgvector | Neon | Shared corpus and tenant-scoped user data live in one database. |
| Cloned voice | Kaggle GPU | Optional and ephemeral; the Cloudflare tunnel URL changes after restart. |

For a production deployment:

1. Apply every database migration.
2. Set the same `DATABASE_URL` for Vercel and Render.
3. Set `AUTH_SECRET` and `NEXT_PUBLIC_API_BASE_URL` on Vercel.
4. Set `ENVIRONMENT=production`, `JINA_API_KEY`, and the exact Vercel origin in `CORS_ALLOW_ORIGINS` on Render.
5. Leave the Render `GEMINI_API_KEY` unset.
6. Set `CHATTERBOX_URL` only while a disclosed synthetic-voice service is running.
7. Run `python scripts/smoke_test.py` against the finished environment.

The repository includes a scheduled GitHub Actions health ping for the current Render service. Treat it as a best-effort availability measure, not a replacement for production monitoring.

## Known constraints

- Generated answers can still be incomplete or wrong, even when retrieved passages are relevant.
- The public corpus is a curated snapshot, not a complete or official archive of Andrew Ng's work.
- Browser speech recognition and browser voices vary by operating system and browser.
- The cloned voice depends on a temporary GPU session and tunnel.
- Free hosting can add cold-start latency.
- Live persona and retrieval evaluations consume external API quota.
- The collected source corpus is intentionally absent from Git history.

## Documentation

| Document | Contents |
|---|---|
| [`architecture.md`](architecture.md) | Deeper backend, retrieval, memory, and database design notes |
| [`persona_contract.md`](persona_contract.md) | Behavioural contract and disclosure rules |
| [`andrew_ng_digital_twin_system_prompt.md`](andrew_ng_digital_twin_system_prompt.md) | Persona and response-policy reference |
| [`docs/VOICE_SETUP.md`](docs/VOICE_SETUP.md) | Local and Kaggle voice configuration |
| [`docs/NEON_SETUP.md`](docs/NEON_SETUP.md) | Hosted PostgreSQL and deployment setup |
| [`docs/PRIVACY.md`](docs/PRIVACY.md) | Storage, third-party processing, and deletion boundaries |
| [`docs/POSTURE.md`](docs/POSTURE.md) | Affiliation, corpus, portrait, and synthetic-voice posture |
| [`scripts/eval/README.md`](scripts/eval/README.md) | Retrieval, persona, and memory evaluation |

## Responsible use

Use the project as an educational system and an experiment in grounded conversational interfaces. Do not present its output as a real statement, recording, endorsement, or decision by Andrew Ng. Respect the copyright and terms attached to every source document, portrait, and voice sample.

No software license is currently included in this repository. Unless a license is added, the code remains under the repository owner's copyright.
