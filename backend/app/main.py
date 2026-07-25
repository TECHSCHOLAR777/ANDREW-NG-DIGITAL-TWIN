"""
main.py
─────────────────────────────────────────────────────────────────────────────
FastAPI application entrypoint.

Environment variables (set in .env or hosting platform):
  DATABASE_URL   : postgresql+asyncpg://user:pass@host/db (PostgreSQL connection string)
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
    db_url_raw = os.environ.get("DATABASE_URL")
    if not db_url_raw:
        raise RuntimeError(
            "DATABASE_URL is not set. Create a .env file with a direct "
            "PostgreSQL connection string, e.g. "
            "DATABASE_URL=postgresql://user:<password>@host/database?sslmode=require"
        )
    db_url = db_url_raw.replace("postgresql+asyncpg://", "postgresql://")
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
    # Preload only when EMBED_PROVIDER=local. External providers make this a no-op.
    from .routers.chat import preload_local_embed_model
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, preload_local_embed_model)

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

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]


app = FastAPI(
    title    = "Andrew Ng Digital Twin API",
    version  = "2.0.0",
    lifespan = lifespan,
    docs_url = None if ENVIRONMENT == "production" else "/docs",
    redoc_url = None if ENVIRONMENT == "production" else "/redoc",
)

# CORS — adjust origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins     = cors_origins,
    # No cookies are used anywhere (auth is header-based), so credentialed
    # CORS would only widen what a malicious origin can do. Keep it off.
    allow_credentials = False,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.include_router(chat.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "2.0.0"}
