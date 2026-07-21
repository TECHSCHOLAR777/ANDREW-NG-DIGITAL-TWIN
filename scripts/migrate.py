"""
scripts/migrate.py
─────────────────────────────────────────────────────────────────────────────
Apply SQL migrations in order and record what has run.

Before this, setup meant opening the Supabase SQL editor and pasting eleven
files in the correct sequence by hand, with the ordering constraints living
only in the README's prose. There was no record of what had been applied, so
the only way to know the state of a database was to inspect it.

Usage:
    python scripts/migrate.py              # apply anything outstanding
    python scripts/migrate.py --status     # show what has and has not run
    python scripts/migrate.py --dry-run    # list what would run, change nothing

Migrations are applied inside a transaction each, so a failure leaves the
database on the last good migration rather than half-way through a broken one.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "backend" / "migrations"

BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def discover() -> list[Path]:
    """Migration files in lexical order, which is why they are zero-padded."""
    if not MIGRATIONS_DIR.is_dir():
        sys.exit(f"No migrations directory at {MIGRATIONS_DIR}")
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def normalise_db_url(raw: str) -> str:
    return raw.replace("postgresql+asyncpg://", "postgresql://")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Apply database migrations in order.")
    parser.add_argument("--status", action="store_true", help="show state and exit")
    parser.add_argument("--dry-run", action="store_true", help="list pending work only")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit(
            "DATABASE_URL is not set.\n"
            "Copy .env.example to .env and fill in your Supabase connection string."
        )

    files = discover()
    if not files:
        sys.exit(f"No .sql files found in {MIGRATIONS_DIR}")

    try:
        conn = await asyncpg.connect(dsn=normalise_db_url(db_url), timeout=15)
    except Exception as exc:  # noqa: BLE001
        # A stack trace here tells the user nothing useful. The realistic
        # causes are a paused Supabase project, a rotated password, or a
        # copied-but-not-edited connection string.
        print(f"\nCould not connect to the database.\n  {type(exc).__name__}: {exc}\n")
        print("Common causes:")
        print("  - The Supabase project is paused (free tier pauses when idle).")
        print("  - The password in DATABASE_URL is wrong or was rotated.")
        print("  - DATABASE_URL still contains the placeholder from .env.example.")
        print("  - The project reference in the host name no longer exists.\n")
        print("Check Settings > Database > Connection string in the Supabase dashboard.")
        return 2

    try:
        await conn.execute(BOOTSTRAP)
        rows = await conn.fetch("SELECT filename, checksum FROM schema_migrations")
        applied = {r["filename"]: r["checksum"] for r in rows}

        pending = [f for f in files if f.name not in applied]

        if args.status or args.dry_run:
            print(f"\nMigrations in {MIGRATIONS_DIR.name}/\n")
            for f in files:
                if f.name in applied:
                    drifted = applied[f.name] != checksum(f)
                    mark = "CHANGED SINCE APPLIED" if drifted else "applied"
                    print(f"  [{'!' if drifted else 'x'}] {f.name:45} {mark}")
                else:
                    print(f"  [ ] {f.name:45} pending")
            print(f"\n{len(pending)} pending, {len(applied)} applied.\n")
            return 0

        # A file edited after being applied will not re-run, and silently
        # diverging schema is worth shouting about.
        for f in files:
            if f.name in applied and applied[f.name] != checksum(f):
                print(
                    f"WARNING: {f.name} has changed since it was applied. "
                    "Migrations are immutable once run; add a new file instead."
                )

        if not pending:
            print("Database is up to date.")
            return 0

        for f in pending:
            print(f"Applying {f.name} ...", flush=True)
            sql = f.read_text(encoding="utf-8")
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        """
                        INSERT INTO schema_migrations (filename, checksum)
                        VALUES ($1, $2)
                        ON CONFLICT (filename) DO UPDATE SET checksum = EXCLUDED.checksum
                        """,
                        f.name, checksum(f),
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"\nFAILED on {f.name}:\n  {exc}\n")
                print("Nothing from this file was applied. Earlier migrations are intact.")
                return 1
            print(f"  done: {f.name}")

        print(f"\nApplied {len(pending)} migration(s). Database is up to date.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
