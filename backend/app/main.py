"""
main.py
─────────────────────────────────────────────────────────────────────────────
FastAPI application entrypoint.

Environment variables (set in .env or hosting platform):
  DATABASE_URL   : postgresql+asyncpg://user:pass@host/db (Supabase connection string)
  ENVIRONMENT    : "development" | "production"

No GEMINI_API_KEY here — all keys come from the client (BYOK pattern).
"""

from __future__ import annotations

import logging
import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import chat

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the asyncpg connection pool lifecycle."""
    db_url = os.environ["DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    # Retry DB connection up to 3 times (handles transient IPv6 routing issues)
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Connecting to database… (attempt %d/%d)", attempt, max_retries)
            app.state.db_pool = await asyncpg.create_pool(
                dsn              = db_url,
                min_size         = 2,
                max_size         = 20,
                command_timeout  = 30,
                statement_cache_size = 0, # Fix prepared statements cache crash on Supabase pooler
                # Register a codec so asyncpg sends Python lists as pgvector columns
                # (pgvector asyncpg integration)
                init             = _register_vector_codec,
            )
            logger.info("Database pool ready.")
            break
        except (OSError, asyncpg.PostgresError, TimeoutError) as e:
            logger.warning("DB connection attempt %d failed: %s", attempt, e)
            if attempt == max_retries:
                raise
            await asyncio.sleep(2 ** attempt)  # exponential backoff: 2s, 4s

    yield
    await app.state.db_pool.close()
    logger.info("Database pool closed.")


async def _register_vector_codec(conn: asyncpg.Connection) -> None:
    """
    Register a custom type codec so Python lists/tuples are serialized
    as pgvector-compatible text literals by asyncpg.
    """
    await conn.set_type_codec(
        "vector",
        encoder = lambda v: "[" + ",".join(str(x) for x in v) + "]",
        decoder = lambda s: [float(x) for x in s.strip("[]").split(",")],
        schema  = "public",
        format  = "text",
    )


app = FastAPI(
    title    = "Andrew Ng Digital Twin API",
    version  = "2.0.0",
    lifespan = lifespan,
)

# CORS — adjust origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["http://localhost:3000", "http://127.0.0.1:3000", "https://your-domain.com"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.include_router(chat.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "2.0.0"}
