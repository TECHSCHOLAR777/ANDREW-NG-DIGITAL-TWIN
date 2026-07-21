"""
scripts/smoke_test.py
─────────────────────────────────────────────────────────────────────────────
Check every dependency the system needs and say precisely which one is missing.

Standing this project up requires a database, migrations, an ingested corpus,
an API key, a running backend, a frontend and optionally a GPU TTS service.
When something does not work, the symptom is usually a generic 500 or an empty
answer, and finding the actual cause means reading logs across three processes.

This checks each layer in dependency order and stops being useful only when
everything passes.

Usage:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _p(check: Check) -> None:
    mark = {OK: " ok ", WARN: "warn", FAIL: "FAIL", SKIP: "skip"}[check.status]
    print(f"  [{mark}] {check.name:<34} {check.detail}")
    if check.fix and check.status in (FAIL, WARN):
        for line in check.fix.splitlines():
            print(f"         -> {line}")


async def run(verbose: bool) -> int:
    from dotenv import load_dotenv
    load_dotenv()

    checks: list[Check] = []

    # ── 1. Configuration ────────────────────────────────────────────────
    print("\nConfiguration")
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        checks.append(Check("DATABASE_URL", FAIL, "not set",
                            "cp .env.example .env, then fill in the Supabase connection string"))
    elif "YOUR_PASSWORD" in db_url or "your_password" in db_url:
        checks.append(Check("DATABASE_URL", FAIL, "still the placeholder",
                            "Settings > Database > Connection string in Supabase"))
    else:
        checks.append(Check("DATABASE_URL", OK, "set"))

    env = os.environ.get("ENVIRONMENT", "development").lower()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env == "production" and key:
        checks.append(Check("GEMINI_API_KEY", WARN,
                            "set in production, where BYOK should apply",
                            "In production every user supplies their own key; this one is unused"))
    elif not key:
        checks.append(Check("GEMINI_API_KEY", WARN, "not set",
                            "Fine if every user brings their own key.\n"
                            "Needed for: building the curriculum, golden sets, evaluations"))
    else:
        checks.append(Check("GEMINI_API_KEY", OK, f"set ({len(key)} chars)"))

    for c in checks:
        _p(c)
    if any(c.status == FAIL for c in checks):
        print("\nStopping: cannot continue without a database URL.\n")
        return 1

    # ── 2. Python dependencies ──────────────────────────────────────────
    print("\nPython packages")
    dep_checks: list[Check] = []
    for module, why in [
        ("asyncpg", "database"),
        ("fastapi", "API"),
        ("sentence_transformers", "embeddings"),
        ("httpx", "outbound HTTP"),
    ]:
        try:
            __import__(module)
            dep_checks.append(Check(module, OK, why))
        except ImportError:
            dep_checks.append(Check(module, FAIL, "not installed",
                                    "pip install -r requirements.txt"))

    try:
        from app.services import gemini_client
        backend = gemini_client.backend_name()
        if backend == "google-genai":
            dep_checks.append(Check("gemini SDK", OK, "google-genai, per-request clients"))
        elif backend == "legacy":
            dep_checks.append(Check("gemini SDK", WARN,
                                    "deprecated google-generativeai only",
                                    "pip install google-genai\n"
                                    "Without it every generation is serialised behind a lock"))
        else:
            dep_checks.append(Check("gemini SDK", FAIL, "none installed",
                                    "pip install google-genai"))
    except Exception as exc:  # noqa: BLE001
        dep_checks.append(Check("gemini SDK", FAIL, str(exc)[:50]))

    for c in dep_checks:
        _p(c)
    checks += dep_checks

    # ── 3. Database ─────────────────────────────────────────────────────
    print("\nDatabase")
    import asyncpg
    conn = None
    try:
        conn = await asyncpg.connect(
            dsn=db_url.replace("postgresql+asyncpg://", "postgresql://"), timeout=15
        )
        _p(Check("connection", OK, "reachable"))
    except Exception as exc:  # noqa: BLE001
        _p(Check("connection", FAIL, f"{type(exc).__name__}: {str(exc)[:60]}",
                 "Common causes:\n"
                 "  Supabase free tier pauses idle projects, open the dashboard to wake it\n"
                 "  password rotated, or project reference no longer exists"))
        print("\nStopping: nothing else can be checked without a database.\n")
        return 1

    try:
        # Migrations
        try:
            applied = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
        except asyncpg.UndefinedTableError:
            applied = 0
        total = len(list((_ROOT / "backend" / "migrations").glob("*.sql")))
        if applied == 0:
            _p(Check("migrations", FAIL, f"none of {total} applied",
                     "python scripts/migrate.py"))
        elif applied < total:
            _p(Check("migrations", FAIL, f"{applied} of {total} applied",
                     "python scripts/migrate.py"))
        else:
            _p(Check("migrations", OK, f"{applied} of {total} applied"))

        # pgvector
        has_vector = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        _p(Check("pgvector", OK if has_vector else FAIL,
                 "installed" if has_vector else "missing",
                 "" if has_vector else "CREATE EXTENSION vector; (migration 001 does this)"))

        # Corpus
        try:
            chunks = await conn.fetchval("SELECT COUNT(*) FROM knowledge_chunks")
            embedded = await conn.fetchval(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL"
            )
            if chunks == 0:
                _p(Check("corpus", FAIL, "no chunks ingested",
                         "python scripts/ingest_supabase.py\n"
                         "Without this every answer is ungrounded"))
            elif embedded < chunks:
                _p(Check("corpus", WARN, f"{embedded} of {chunks} chunks embedded",
                         "Re-run scripts/ingest_supabase.py to finish"))
            else:
                _p(Check("corpus", OK, f"{chunks} chunks, all embedded"))
        except asyncpg.UndefinedTableError:
            _p(Check("corpus", FAIL, "table missing", "python scripts/migrate.py"))

        # Vector index type. IVFFlat built pre-ingest has degraded recall,
        # which is silent, so it is worth naming explicitly.
        try:
            idx = await conn.fetchval(
                """
                SELECT indexdef FROM pg_indexes
                WHERE tablename = 'knowledge_chunks' AND indexdef ILIKE '%USING%'
                  AND (indexdef ILIKE '%hnsw%' OR indexdef ILIKE '%ivfflat%')
                LIMIT 1
                """
            )
            if idx and "hnsw" in idx.lower():
                _p(Check("vector index", OK, "HNSW"))
            elif idx:
                _p(Check("vector index", WARN, "still IVFFlat",
                         "Apply migration 008; IVFFlat built before ingest has poor recall"))
            else:
                _p(Check("vector index", WARN, "none found", "Apply migration 008"))
        except Exception:  # noqa: BLE001
            pass

        # Curriculum, optional
        try:
            concepts = await conn.fetchval("SELECT COUNT(*) FROM curriculum_concepts")
            edges = await conn.fetchval("SELECT COUNT(*) FROM curriculum_edges")
            if concepts:
                _p(Check("curriculum", OK, f"{concepts} concepts, {edges} prerequisites"))
            else:
                _p(Check("curriculum", SKIP, "not built (optional)",
                         "python scripts/build_curriculum.py --out data/baselines/curriculum.json\n"
                         "then --load it. Without it: no learning paths or gap diagnosis"))
        except asyncpg.UndefinedTableError:
            _p(Check("curriculum", SKIP, "migration 012 not applied (optional)"))
    finally:
        await conn.close()

    # ── 4. Corpus files on disk ─────────────────────────────────────────
    print("\nLocal files")
    cleaned = _ROOT / "data" / "cleaned"
    n_files = len(list(cleaned.glob("**/*.txt"))) if cleaned.is_dir() else 0
    _p(Check("data/cleaned", OK if n_files else WARN,
             f"{n_files} documents" if n_files else "empty",
             "" if n_files else "Needed to re-ingest or build a curriculum.\n"
                               "Run the scripts/collect_*.py scrapers"))

    ref = _ROOT / "backend" / "data" / "andrew_ng_ref.wav"
    _p(Check("voice reference", OK if ref.exists() else SKIP,
             "present" if ref.exists() else "absent (voice cloning disabled)"))

    # ── 5. Services ─────────────────────────────────────────────────────
    print("\nServices")
    import httpx

    api_base = os.environ.get("SMOKE_API_BASE", "http://127.0.0.1:8000")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{api_base}/health")
        _p(Check("backend", OK if r.status_code == 200 else WARN,
                 f"HTTP {r.status_code} at {api_base}"))
    except Exception:  # noqa: BLE001
        _p(Check("backend", WARN, "not running",
                 "python -m uvicorn backend.app.main:app --reload"))

    tts_url = os.environ.get("CHATTERBOX_URL", "http://127.0.0.1:5002/v1/audio/speech")
    health = tts_url.replace("/v1/audio/speech", "/health")
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(health)
        if r.status_code == 200:
            info = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            device = info.get("device", "unknown")
            wm = info.get("watermarking")
            detail = f"reachable, device={device}"
            if wm is False:
                detail += ", WATERMARKING OFF"
            _p(Check("cloned voice", OK, detail))
        else:
            _p(Check("cloned voice", SKIP, f"HTTP {r.status_code}"))
    except Exception:  # noqa: BLE001
        _p(Check("cloned voice", SKIP, "unreachable (browser speech will be used)",
                 "No local GPU? Run notebooks/kaggle_tts_server.py on Kaggle,\n"
                 "then set CHATTERBOX_URL to the printed tunnel URL"))

    print("\nDone. Items marked FAIL block end-to-end use; warn and skip do not.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the system end to end.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.verbose))


if __name__ == "__main__":
    sys.exit(main())
