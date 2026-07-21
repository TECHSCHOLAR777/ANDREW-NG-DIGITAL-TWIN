# Moving to Neon, and Deploying

Complete path from a dead database to a deployed system.

## Why Neon rather than Supabase

Your Supabase project returns `(ENOTFOUND) tenant/user postgres.<ref> not
found`, which means it was deleted, paused, or its credentials rotated.

The failure mode matters more than the incident. **Supabase free tier pauses
projects after about a week of inactivity and requires a dashboard visit to
resume.** For a project you want to show people, that means the demo is dead
exactly when someone clicks the link.

Neon also scales to zero, but **wakes automatically on the next connection** in
roughly 500ms. Same cost, no manual intervention. That is the entire reason for
the switch.

Nothing in this codebase is Supabase-specific. It is plain Postgres plus
pgvector, so the migration is a connection string change and two commands.

---

## Part 1: Create the database

### 1.1 Create the project

1. Sign up at [neon.tech](https://neon.tech) (GitHub login works).
2. Create a project.
3. **Region: pick the one closest to where the backend will run**, not to you.
   Every turn makes several database round trips, so backend-to-database
   latency multiplies. If you deploy to Singapore, choose Singapore.
4. Postgres 16 or later.

### 1.2 Get the connection string

Dashboard, **Connection Details**. You will see two options.

**Take the direct connection, not the pooled one.**

```
# Correct, direct:
postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require

# Wrong for this project, pooled:
postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require
```

The pooler is PgBouncer in transaction mode, which disables prepared
statements. asyncpg uses prepared statements for every query, so the pooled
endpoint fails in confusing ways rather than cleanly. The distinguishing
detail is `-pooler` in the hostname.

### 1.3 Enable pgvector

Neon ships the extension but it must be enabled per database. Use the SQL
Editor in the dashboard:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Migration 001 also does this, so you can skip it, but doing it first turns a
confusing migration failure into a clear one.

### 1.4 Point the project at it

In `.env`:

```bash
DATABASE_URL=postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require
```

`sslmode=require` is not optional. Neon rejects unencrypted connections.

### 1.5 Verify

```bash
python scripts/smoke_test.py
```

The database section should report `connection ok`. If it does not, the message
names the cause.

---

## Part 2: Build the schema and corpus

### 2.1 Migrations

```bash
python scripts/migrate.py --status   # what would run
python scripts/migrate.py            # apply all twelve
```

Each runs in its own transaction, so a failure leaves you on the last good
migration rather than half-applied.

**These have never run against a live database.** Treat this as a shakedown. If
migration 009 fails on duplicate live triples, that is correct behaviour on
pre-existing data; tell me and I will write the dedup. On a fresh Neon database
there is no pre-existing data, so this should be clean.

### 2.2 Ingest the corpus

```bash
python scripts/ingest_supabase.py
```

Twenty to forty minutes. Embeddings are computed locally on CPU, which is the
slow part. The script is idempotent: it compares chunk counts per file and
skips what is already loaded, so an interrupted run can be resumed.

### 2.3 Rebuild the vector index

**Do not skip this.** HNSW built before data exists has the same silent recall
problem that made the original IVFFlat index useless.

```sql
REINDEX INDEX idx_knowledge_chunks_embedding_hnsw;
```

### 2.4 Verify

```bash
python scripts/smoke_test.py
```

Expect: all migrations applied, chunks ingested and embedded, vector index
HNSW.

### 2.5 Optional: build the curriculum

```bash
python scripts/build_curriculum.py --out data/baselines/curriculum.json
# review the JSON before loading
python scripts/build_curriculum.py --load data/baselines/curriculum.json
```

Without it, learning paths and gap diagnosis stay off and everything else works.

---

## Part 3: Neon specifics that affect this codebase

### Autosuspend and the first request

Neon suspends compute after five minutes idle and wakes on connection. The
first query after a suspend takes roughly 500ms to 2s.

The backend already handles this: `main.py` retries the initial pool connection
three times with exponential backoff. Nothing to change, but if the very first
request after a long idle feels slow, this is why.

To eliminate it, disable autosuspend in Neon settings. That consumes compute
hours continuously, so on the free tier it will exhaust your monthly allowance.
Leave it on.

### Connection limits

Neon's free tier allows fewer concurrent connections than a dedicated Postgres.
The pool in `main.py` is `min_size=2, max_size=20`, which is fine for one
backend instance but too high if you run several.

If you see connection limit errors, lower it:

```python
# backend/app/main.py
app.state.db_pool = await asyncpg.create_pool(
    dsn=db_url, min_size=1, max_size=10, ...
)
```

### Storage

Free tier is 0.5GB. Your corpus is about 11MB of text; with embeddings and
indexes expect roughly 150 to 250MB. Comfortable, but not unlimited.

### Branching

Neon can branch a database like git, copy-on-write. Genuinely useful here: run
the evaluation harness against a branch so a bad curriculum load or a failed
migration does not touch your working data.

```bash
# Create a branch in the dashboard, then point at it temporarily
DATABASE_URL=<branch-connection-string> python scripts/retrieval_eval.py
```

---

## Part 4: Deployment

### The shape

```
Vercel                Render or Fly.io           Neon
──────                ────────────────           ────
Next.js frontend ───► FastAPI backend      ───►  Postgres + pgvector
                             │
                             └──────────────►    Kaggle GPU (TTS, optional)
```

### 4.1 Why the backend cannot go on Vercel

The backend loads `all-mpnet-base-v2` into memory, which needs about 2GB RAM
and a persistent process. Vercel functions are serverless with tight memory
limits and cold starts, so the model would reload constantly.

Use a container host. **Render** is simplest; **Fly.io** gives better region
control, which matters because you want the backend near Neon.

### 4.2 Deploy the backend

The `Dockerfile` is already multi-stage, runs unprivileged, has a healthcheck
and bakes the embedding model into the image so first request does not pay for
a 420MB download.

**Render:**
1. New, Web Service, connect the repository.
2. Runtime: Docker. Dockerfile path: `./Dockerfile`.
3. Instance type: **at least 2GB RAM**. The free 512MB tier cannot load the
   embedding model and will restart in a loop.
4. Region: the same continent as your Neon project.
5. Environment variables:

```bash
DATABASE_URL=<neon direct connection string>
ENVIRONMENT=production
CORS_ALLOW_ORIGINS=https://your-frontend.vercel.app
# No GEMINI_API_KEY. In production every user supplies their own.
CHATTERBOX_URL=<Kaggle tunnel, or omit for browser speech>
RATE_LIMIT_CHAT=20
```

**`ENVIRONMENT=production` matters.** It disables the server-side key fallback,
so anonymous visitors cannot bill your Gemini quota. Leaving it at
`development` on a public URL is the single most expensive mistake available.

### 4.3 Deploy the frontend

**Vercel:**
1. Import the repository, root directory `frontend`.
2. Environment variable:

```bash
NEXT_PUBLIC_API_BASE_URL=https://your-backend.onrender.com
```

`NEXT_PUBLIC_*` values are inlined at build time, so changing this requires a
redeploy, not just a restart.

3. Deploy, then **go back and set `CORS_ALLOW_ORIGINS` on the backend** to the
   Vercel URL. The two reference each other, so one of them is always
   configured second.

### 4.4 Run migrations against production

```bash
DATABASE_URL=<neon production string> python scripts/migrate.py
```

Ingestion can run from your laptop against the production database. It is
network-bound on insert and CPU-bound on embedding, so running it locally is
fine and avoids paying for compute on the host.

### 4.5 Verify the deployment

```bash
curl https://your-backend.onrender.com/health

SMOKE_API_BASE=https://your-backend.onrender.com python scripts/smoke_test.py
```

Then open the frontend and send a message. Watch the backend logs: you should
see the turn classified, retrieval reporting hits and a cosine score, and
extraction running in the background.

### 4.6 Before making the URL public

From `docs/POSTURE.md`, and these are not optional:

- `ENVIRONMENT=production` confirmed, so BYOK is enforced.
- The unofficial-recreation line visible in the interface.
- `docs/PRIVACY.md` linked, including that free-tier Gemini content may be used
  for model training.
- Do not use Andrew Ng's name in the domain.
- Serve a non-cloned voice publicly. The Kaggle clone is a local demo.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ENOTFOUND` or `tenant/user not found` | Wrong host or deleted project | Re-copy the connection string |
| `prepared statement "__asyncpg_" already exists` | Using the pooled endpoint | Use the direct one, without `-pooler` |
| `SSL required` | Missing SSL parameter | Append `?sslmode=require` |
| First request slow, then fast | Neon autosuspend waking | Expected. Retry logic handles it |
| `too many connections` | Pool too large for the tier | Lower `max_size` in `main.py` |
| Backend restarts in a loop | Under 2GB RAM | Larger instance |
| Answers ungrounded, `is_grounded: false` everywhere | Corpus not ingested, or index built empty | Ingest, then `REINDEX` |
| CORS errors in the browser | `CORS_ALLOW_ORIGINS` missing the frontend URL | Set it exactly, including `https://` |

---

## Cost

| Component | Free tier | If you outgrow it |
|---|---|---|
| Neon | 0.5GB storage, autosuspend | ~$19/mo |
| Render backend | Not viable, needs 2GB | ~$7 to $25/mo |
| Vercel frontend | Generous, fine indefinitely | free |
| Gemini | Users bring their own keys | $0 to you |
| Kaggle GPU | 30 GPU hours weekly | free |

The BYOK design means the expensive part, generation, costs you nothing. Your
floor is the backend instance.
