"""
scripts/ingest_supabase.py
─────────────────────────────────────────────────────────────────────────────
Uploads the local cleaned corpus to your Supabase PostgreSQL DB.
Uses Gemini's text-embedding-004 API (768-dim) and asyncpg.

Safety Cap:
  The Gemini developer API free tier allows a maximum of 15 Requests Per Minute
  (RPM). To prevent rate limit errors, this script implements an explicit 4.1s
  sleep between embedding API calls.

Requirements:
  pip install asyncpg google-generativeai python-dotenv tqdm
"""

import os
import re
import asyncio
import logging
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
import asyncpg
from tqdm import tqdm

load_dotenv()

# Configuration
CLEANED_DIR = Path("data/cleaned")
# Embeddings are computed locally with sentence-transformers (768 dims).
# Must match EMBED_MODEL used by the backend at query time, or vectors from
# ingestion and vectors from search will live in different spaces.
EMBEDDING_MODEL = os.environ.get("EMBED_MODEL", "all-mpnet-base-v2")
DEFAULT_TENANT_NAME = "Andrew Ng Digital Twin"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Parse Metadata Headers ──────────────────────────────────────────────────
def parse_metadata_headers(content: str) -> tuple[dict, str]:
    lines = content.splitlines()
    metadata = {}
    body_start_idx = 0
    
    for idx, line in enumerate(lines):
        if line.startswith("# Title:"):
            metadata["title"] = line.replace("# Title:", "").strip()
        elif line.startswith("# URL:"):
            metadata["url"] = line.replace("# URL:", "").strip()
        elif line.startswith("# Date:"):
            metadata["date"] = line.replace("# Date:", "").strip()
        elif line.startswith("# Domain:"):
            metadata["domain"] = line.replace("# Domain:", "").strip()
        elif line.startswith("=" * 10) or line.startswith("-" * 10):
            body_start_idx = idx + 1
            break
        elif not line.startswith("#") and line.strip() != "":
            body_start_idx = idx
            break
            
    body_text = "\n".join(lines[body_start_idx:])
    return metadata, body_text.strip()

# ── Split Document into Chunks ────────────────────────────────────────────────
# Structure-aware chunking lives in scripts/chunking.py. The previous
# implementation packed paragraphs to 1000 characters with no overlap and no
# titles, so a retrieved chunk frequently began mid-explanation and used
# notation the previous chunk had introduced.
from chunking import chunk_document  # noqa: E402


_local_model = None

# ── Fetch Embeddings locally using sentence-transformers ──────────────────────
def get_embeddings_local(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    from sentence_transformers import SentenceTransformer
    global _local_model
    if _local_model is None:
        logger.info("Loading local SentenceTransformer model '%s'...", EMBEDDING_MODEL)
        _local_model = SentenceTransformer(EMBEDDING_MODEL)
    
    return _local_model.encode(texts, show_progress_bar=True, batch_size=128).tolist()


async def ensure_corpus_tenant(conn: asyncpg.Connection) -> uuid.UUID:
    """Return the stable tenant id that owns the shared Andrew corpus."""
    configured_id = os.environ.get("CORPUS_TENANT_ID", "").strip()
    if configured_id:
        try:
            tenant_id = uuid.UUID(configured_id)
            await conn.execute(
                """
                INSERT INTO tenants (id, name)
                VALUES ($1::uuid, $2)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """,
                tenant_id,
                DEFAULT_TENANT_NAME,
            )
            return tenant_id
        except Exception as exc:
            raise ValueError(f"Invalid or unusable CORPUS_TENANT_ID={configured_id}") from exc

    tenant_id = await conn.fetchval(
        "SELECT id FROM tenants WHERE name = $1 ORDER BY created_at ASC LIMIT 1",
        DEFAULT_TENANT_NAME,
    )
    if tenant_id:
        return tenant_id

    return await conn.fetchval(
        """
        INSERT INTO tenants (name)
        VALUES ($1)
        RETURNING id
        """,
        DEFAULT_TENANT_NAME,
    )

# ── Main Ingestion Runner ─────────────────────────────────────────────────────
async def main():
    db_url = os.environ.get("DATABASE_URL")

    if not db_url:
        logger.error("DATABASE_URL env var is missing.")
        return

    # Normalize DB URL for asyncpg
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    # Connect briefly to fetch tenant_id and pre-cache existing database files
    logger.info("Connecting to Supabase to fetch initial metadata...")
    conn = await asyncpg.connect(dsn=db_url)

    # 1. Ensure a stable shared-corpus tenant exists
    tenant_id = await ensure_corpus_tenant(conn)

    logger.info("Using Tenant ID: %s", tenant_id)

    # Pre-fetch all ingested files and counts in a single query
    rows = await conn.fetch(
        "SELECT source_file, COUNT(*) as count FROM knowledge_chunks WHERE tenant_id = $1 GROUP BY source_file",
        tenant_id
    )
    db_files = {r["source_file"]: r["count"] for r in rows}
    
    await conn.close()
    logger.info("Cached %d ingested files from database.", len(db_files))

    logger.info("Scanning data/cleaned/ directory for source files...")
    all_files = list(CLEANED_DIR.glob("**/*.txt"))
    logger.info("Found %d files to ingest.", len(all_files))

    if not all_files:
        logger.error("No cleaned text files found in data/cleaned/. Ingestion aborted.")
        return

    # 2. Scan and identify pending chunks to embed locally
    pending_chunks = []
    pbar = tqdm(all_files, desc="Scanning local files against database")
    
    for file_path in pbar:
        source_file = file_path.name
        pbar.set_postfix_str(source_file)
        
        # Categorize source type
        source_type = "lecture"
        parent_name = file_path.parent.name
        if parent_name in ["transcripts", "the_batch", "blog_posts"]:
            source_type = parent_name.replace("the_batch", "newsletter")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Clean null bytes
        content = content.replace("\x00", "").replace("\u0000", "")

        meta, body_text = parse_metadata_headers(content)
        doc_title = meta.get("title") or file_path.stem.replace("_", " ")
        chunks = chunk_document(body_text, doc_title=doc_title)

        # Idempotency check using local cache
        db_chunk_count = db_files.get(source_file, 0)
        
        if db_chunk_count == len(chunks):
            # Fully ingested, skip
            continue
        elif db_chunk_count > 0:
            # Partially ingested, delete so we can clean-ingest it
            logger.info("Partial upload detected for %s (%d/%d chunks). Resetting...", source_file, db_chunk_count, len(chunks))
            conn = await asyncpg.connect(dsn=db_url)
            await conn.execute(
                "DELETE FROM knowledge_chunks WHERE tenant_id = $1 AND source_file = $2",
                tenant_id,
                source_file
            )
            await conn.close()
            db_files[source_file] = 0

        for idx, chunk in enumerate(chunks):
            pending_chunks.append({
                "tenant_id": tenant_id,
                "source_file": source_file,
                "source_type": source_type,
                "chunk_index": idx,
                # Stored text stays clean for display...
                "chunk_text": chunk.text,
                # ...while the embedded text carries the heading trail, so a
                # fragment about "the update rule" is no longer identical in
                # vector space to every other update rule in the corpus.
                "embed_text": chunk.embed_text,
            })

    if not pending_chunks:
        logger.info("Everything is up-to-date! Database is already fully loaded.")
        return

    logger.info("Found %d pending chunks to embed across files.", len(pending_chunks))
    
    # 3. Retrieve embeddings for pending chunks in batches of 200
    batch_size = 200
    total_chunks = len(pending_chunks)
    
    for i in range(0, total_chunks, batch_size):
        batch = pending_chunks[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total_chunks + batch_size - 1) // batch_size
        
        logger.info("Processing Ingestion Batch %d/%d (size %d)...", batch_num, total_batches, len(batch))
        
        # 3a. Compute embeddings locally (no DB connection active)
        texts_to_embed = [c["embed_text"] for c in batch]
        try:
            vectors = get_embeddings_local(texts_to_embed)
        except Exception as e:
            logger.error("Failed to fetch local embeddings for batch %d: %s", batch_num, e)
            return

        # 3b. Open DB connection briefly for bulk insert
        logger.info("Connecting to Supabase to insert batch %d/%d...", batch_num, total_batches)
        conn = await asyncpg.connect(dsn=db_url)
        
        insert_data = [
            (
                c["tenant_id"],
                c["source_file"],
                c["source_type"],
                c["chunk_index"],
                c["chunk_text"],
                str(vector),
                True,   # is_shared: this is the public Andrew corpus
            )
            for c, vector in zip(batch, vectors)
        ]

        try:
            await conn.executemany(
                """
                INSERT INTO knowledge_chunks
                    (tenant_id, source_file, source_type, chunk_index, chunk_text,
                     embedding, is_shared)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7)
                """,
                insert_data
            )
        except Exception as e:
            logger.error("Database insertion failed for batch %d: %s", batch_num, e)
            await conn.close()
            return

        # 3c. Close DB connection immediately after the batch is uploaded
        await conn.close()
    logger.info("Ingestion complete! Database is loaded and ready.")

if __name__ == "__main__":
    asyncio.run(main())
