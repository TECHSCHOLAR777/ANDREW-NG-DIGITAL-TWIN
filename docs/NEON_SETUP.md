# Neon Database and Deployment Setup

This guide covers a clean PostgreSQL setup and the current Vercel, Render, and
Neon deployment.

## Deployment shape

```mermaid
flowchart LR
    Browser["Browser"]
    Vercel["Vercel<br/>Next.js and Auth.js"]
    Render["Render<br/>FastAPI"]
    Neon[("Neon<br/>PostgreSQL and pgvector")]
    Jina["Jina embeddings"]
    Gemini["Gemini<br/>visitor's key"]
    Voice["Optional TTS service"]

    Browser --> Vercel
    Browser -->|"REST and SSE"| Render
    Vercel --> Neon
    Render --> Neon
    Render --> Jina
    Render --> Gemini
    Render --> Voice
```

The frontend connects to Neon for account creation and authentication. The
backend uses the same database for the shared corpus, sessions, and
tenant-scoped memory.

## 1. Create the database

Create a Neon PostgreSQL project near the Render region to reduce round-trip
latency. Copy a direct connection string:

```text
postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
```

The project uses asyncpg prepared statements. Prefer the direct Neon endpoint.
If you deliberately use a transaction-pooler endpoint, the backend connection
configuration must be adjusted for that mode.

Enable pgvector:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Migration 001 also creates the extension, but running this command first gives
a clearer failure if the database role cannot manage extensions.

## 2. Configure local tooling

Copy the environment template:

```powershell
Copy-Item .env.example .env
```

Set at least:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
EMBED_PROVIDER=jina
JINA_API_KEY=your_jina_key
EMBED_DIMS=1024
ENVIRONMENT=development
```

Ingestion and live retrieval must use the same embedding provider, model, and
dimensions. The deployed corpus uses Jina `jina-embeddings-v3` at 1024
dimensions.

## 3. Apply migrations

The repository currently contains 17 ordered migrations.

Check the target before changing it:

```bash
python scripts/migrate.py --status
python scripts/migrate.py --dry-run
```

Apply pending migrations:

```bash
python scripts/migrate.py
```

Each file runs in its own transaction and is recorded with a checksum in
`schema_migrations`.

> [!CAUTION]
> Migration `014_voyage_embeddings_1024.sql` changes vector width from 768 to
> 1024 and deletes existing `knowledge_chunks` before the change. This is
> correct for a fresh database or a deliberate corpus re-embedding. On an
> established database, inspect `--status` and back up the database before
> applying it.

Do not edit an applied migration. Add a new numbered migration instead.

## 4. Ingest the corpus

Source documents are intentionally absent from Git. Prepare them under the
ignored data directories, then run:

```bash
python scripts/ingest_supabase.py
```

The filename is historical. The script targets standard PostgreSQL and works
with Neon.

After a full ingest, rebuild the HNSW index over the settled data:

```sql
REINDEX INDEX idx_knowledge_chunks_embedding_hnsw;
```

Verify database, migration, corpus, embedding, and service status:

```bash
python scripts/smoke_test.py
```

If a curriculum graph is required:

```bash
python scripts/build_curriculum.py --out data/baselines/curriculum.json
python scripts/build_curriculum.py --load data/baselines/curriculum.json
```

Review the generated JSON before loading it.

## 5. Run locally

Start the backend:

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Create `frontend/.env.local`:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
AUTH_SECRET=replace_with_a_long_random_secret
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Start the frontend:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`.

## 6. Deploy the backend to Render

Create a Web Service from the repository using the root `Dockerfile`.

Configure:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
ENVIRONMENT=production
CORS_ALLOW_ORIGINS=https://your-project.vercel.app
EMBED_PROVIDER=jina
JINA_API_KEY=your_jina_key
JINA_EMBED_MODEL=jina-embeddings-v3
EMBED_DIMS=1024
CORPUS_TENANT_ID=your_shared_corpus_tenant_uuid
```

Optional settings include:

```dotenv
CHATTERBOX_URL=https://your-authorized-tts-service/v1/audio/speech
RATE_LIMIT_CHAT=20
RATE_LIMIT_TTS=120
RATE_LIMIT_READ=240
```

Do not configure `GEMINI_API_KEY` on a public backend. With
`ENVIRONMENT=production`, each generation request must carry the visitor's
`X-Gemini-Api-Key`.

The default Jina embedding path does not load PyTorch or model weights into the
API container. A local embedding provider requires
`requirements-local-embeddings.txt` and substantially more memory.

Verify Render:

```bash
curl https://your-render-service.onrender.com/health
```

Free or scale-to-zero hosting can add cold-start latency. The streaming route
emits an accepted event and periodic heartbeats so the browser can distinguish
a slow start from a dead request.

## 7. Deploy the frontend to Vercel

Import the repository and set the project root to `frontend`.

Configure:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
AUTH_SECRET=replace_with_a_production_secret
NEXT_PUBLIC_API_BASE_URL=https://your-render-service.onrender.com
```

`NEXT_PUBLIC_API_BASE_URL` is embedded into the client build. Redeploy after
changing it.

After Vercel assigns the production URL, copy that exact origin into Render's
`CORS_ALLOW_ORIGINS` and restart the backend.

## 8. Verify the deployed system

Run the smoke test against the public API:

```powershell
$env:SMOKE_API_BASE='https://your-render-service.onrender.com'
python scripts/smoke_test.py
```

Then check:

1. account creation and sign-in;
2. a streamed chat response;
3. a browser refresh restoring the same session;
4. session deletion;
5. full memory reset;
6. session and global graph views;
7. browser voice fallback with the cloned service offline.

Microphone and cloned-voice testing require explicit user interaction and
should be performed manually in a supported browser.

## Database operations

### Connection limits

`backend/app/main.py` creates an asyncpg pool. If the database reports
connection pressure, lower `max_size` before adding API replicas. Every replica
creates its own pool.

### Autosuspend

Neon can suspend idle compute and wake it on the next connection. Keep retry
logic enabled and expect the first database operation after an idle period to
be slower.

### Branches and backups

Use a Neon branch or backup before:

- testing destructive migrations;
- changing embedding dimensions;
- rebuilding a production corpus;
- running evaluation scenarios that write memory.

### Shared corpus protection

Set `CORPUS_TENANT_ID` to the tenant that owns the shared corpus. Full reset
must never delete that tenant's corpus data.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Connection timeout or DNS failure | Incorrect or expired connection string | Copy the current direct Neon connection string |
| SSL error | Missing SSL requirement | Add `?sslmode=require` |
| Prepared-statement error | Transaction pooler used with default asyncpg settings | Use the direct endpoint or configure pooler-compatible connections |
| Migration checksum warning | An applied SQL file was edited | Restore it and create a new migration |
| Corpus disappears while applying migration 014 | Expected destructive vector-width migration | Restore from backup or re-ingest the corpus |
| Every response is ungrounded | Corpus absent, wrong embedding provider, or dimension mismatch | Run the smoke test and compare provider, model, and dimensions |
| CORS failure | Vercel origin missing or not exact | Set the complete HTTPS origin in `CORS_ALLOW_ORIGINS` |
| Backend restarts with local embeddings | Container lacks memory for PyTorch and model weights | Use Jina or allocate a larger instance |
| Sign-in works locally but not on Vercel | Missing frontend database URL or Auth.js secret | Configure `DATABASE_URL` and `AUTH_SECRET` in Vercel |

## Security checklist

- Keep `.env` and `frontend/.env.local` out of Git.
- Rotate any credential pasted into a chat, issue, log, or screenshot.
- Use different Auth.js secrets for local and production environments.
- Leave the production backend `GEMINI_API_KEY` unset.
- Restrict CORS to the production frontend origin.
- Keep the voice reference sample private.
- Review [`PRIVACY.md`](PRIVACY.md) and [`POSTURE.md`](POSTURE.md) before making
  the deployment public.
