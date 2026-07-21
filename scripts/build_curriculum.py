"""
scripts/build_curriculum.py
─────────────────────────────────────────────────────────────────────────────
Extract a prerequisite DAG of machine learning concepts from the corpus.

WHY THIS IS A SEPARATE OFFLINE STEP
───────────────────────────────────
Every concept in the knowledge graph until now came from conversation, which
means the graph only ever knew things the student had already said. This builds
the other half: the structure of the subject itself, extracted once from what
Andrew has written, independent of any user.

The output is a reviewable JSON file, committed alongside the code, and loading
it into the database is a separate command. That split is deliberate:

  * The expensive LLM pass runs once, not on every deploy.
  * The DAG is a versioned artifact a human can read and correct, rather than
    an opaque table that appeared from a model.
  * A bad extraction is a diff, not a mystery.

CS229 notes and Machine Learning Yearning are unusually good source material
for this, because they are already ordered by dependency.

Usage:
    python scripts/build_curriculum.py --out data/baselines/curriculum.json
    python scripts/build_curriculum.py --load data/baselines/curriculum.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

CORPUS_DIR = _ROOT / "data" / "cleaned"

# Only documents that actually teach in dependency order. Newsletters and blog
# posts discuss concepts without building them, so mining them for
# prerequisites produces plausible-looking noise.
STRUCTURED_HINTS = ("cs229", "yearning", "lecture", "notes")

EXTRACTION_PROMPT = """You are mapping the prerequisite structure of machine learning.

From the passage below, extract concept pairs where one concept must be
understood BEFORE another can be understood.

Rules:
- Only extract a pair when the dependency is real and pedagogical. "Chain rule
  before backpropagation" is real. "Introduced earlier in the chapter" is not.
- Use short canonical concept names: "Gradient Descent", not "the gradient
  descent optimisation algorithm".
- Do NOT invent dependencies that are merely topical. Two concepts appearing in
  the same paragraph is not a prerequisite relationship.
- Assign each concept a difficulty: "intuitive" (needs no maths), "applied"
  (needs some notation), or "formal" (needs real derivation).
- If the passage teaches no dependency, return an empty array. This is common
  and correct.

Return ONLY a JSON array:
[
  {
    "prerequisite": "Chain Rule",
    "concept": "Backpropagation",
    "confidence": 0.9,
    "evidence": "short quote showing the dependency",
    "prerequisite_difficulty": "applied",
    "concept_difficulty": "formal"
  }
]

Passage:
---
{passage}
---
"""


def normalise(name: str) -> str:
    """Must match normalise_concept() in migration 012 and curriculum.normalise."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").strip().lower()).strip()


def structured_documents() -> list[Path]:
    if not CORPUS_DIR.is_dir():
        sys.exit(f"No corpus at {CORPUS_DIR}")
    files = sorted(CORPUS_DIR.glob("**/*.txt"))
    picked = [f for f in files if any(h in f.name.lower() for h in STRUCTURED_HINTS)]
    return picked or files


def _extract(passage: str, api_key: str) -> list[dict]:
    from app.services import gemini_client

    result = gemini_client.generate_sync(
        api_key=api_key,
        model=os.getenv("REWRITE_MODEL", "gemini-2.5-flash"),
        contents=[{"role": "user", "parts": [{"text": EXTRACTION_PROMPT.replace("{passage}", passage[:6000])}]}],
        temperature=0.1,
        max_output_tokens=2048,
        thinking_budget=256,
    )
    raw = (result.text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _drop_cycles(edges: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """
    Remove edges that would create a cycle, keeping the more confident one.

    Language models will occasionally assert both "A before B" and "B before A"
    from different passages. A prerequisite graph with a cycle is not a
    curriculum, so the weaker claim is dropped rather than stored and
    worked around at query time.
    """
    by_conf = sorted(edges, key=lambda e: -float(e.get("confidence", 0.8)))
    kept: list[dict] = []
    prereqs: dict[str, set[str]] = defaultdict(set)
    removed: list[tuple[str, str]] = []

    def reaches(start: str, goal: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(prereqs.get(node, ()))
        return False

    for edge in by_conf:
        p, c = edge["prerequisite"], edge["concept"]
        if p == c:
            continue
        # Adding p->c is safe unless c is already upstream of p.
        if reaches(p, c):
            removed.append((p, c))
            continue
        prereqs[c].add(p)
        kept.append(edge)

    return kept, removed


async def build(limit: int | None, api_key: str) -> dict:
    from chunking import chunk_document
    from ingest_supabase import parse_metadata_headers

    docs = structured_documents()
    if limit:
        docs = docs[:limit]
    print(f"Reading {len(docs)} structured document(s)")

    concepts: dict[str, dict] = {}
    raw_edges: list[dict] = []

    for path in docs:
        raw = path.read_text(encoding="utf-8", errors="ignore").replace("\x00", "")
        meta, body = parse_metadata_headers(raw)
        title = meta.get("title") or path.stem.replace("_", " ")
        chunks = chunk_document(body, doc_title=title)
        print(f"  {path.name[:46]:48} {len(chunks)} passages")

        for i, chunk in enumerate(chunks, 1):
            if len(chunk.text) < 500:
                continue   # too little context to judge a dependency
            for item in _extract(chunk.text, api_key):
                try:
                    p_disp = str(item["prerequisite"]).strip()
                    c_disp = str(item["concept"]).strip()
                    p, c = normalise(p_disp), normalise(c_disp)
                    if not p or not c or p == c:
                        continue

                    for key, disp, diff in (
                        (p, p_disp, item.get("prerequisite_difficulty", "applied")),
                        (c, c_disp, item.get("concept_difficulty", "applied")),
                    ):
                        entry = concepts.setdefault(key, {
                            "name": key, "display_name": disp,
                            "difficulty": diff if diff in ("intuitive", "applied", "formal") else "applied",
                            "source_files": [],
                        })
                        if path.name not in entry["source_files"]:
                            entry["source_files"].append(path.name)

                    raw_edges.append({
                        "prerequisite": p,
                        "concept": c,
                        "confidence": float(item.get("confidence", 0.8)),
                        "evidence": str(item.get("evidence", ""))[:200],
                    })
                except (KeyError, ValueError, TypeError):
                    continue

            if i % 25 == 0:
                print(f"    {i}/{len(chunks)} passages, {len(raw_edges)} edges so far", flush=True)

    # Merge duplicates, keeping the strongest claim for each pair.
    merged: dict[tuple[str, str], dict] = {}
    for e in raw_edges:
        key = (e["prerequisite"], e["concept"])
        if key not in merged or e["confidence"] > merged[key]["confidence"]:
            merged[key] = e

    edges, removed = _drop_cycles(list(merged.values()))

    print(f"\n{len(concepts)} concepts, {len(edges)} edges "
          f"({len(raw_edges) - len(merged)} duplicates merged, "
          f"{len(removed)} cycle-forming edges dropped)")
    if removed:
        print("  dropped to keep the graph acyclic:")
        for p, c in removed[:5]:
            print(f"    {p} -> {c}")

    return {"concepts": list(concepts.values()), "edges": edges}


async def load(path: Path) -> int:
    import asyncpg
    from dotenv import load_dotenv
    load_dotenv()

    data = json.loads(path.read_text(encoding="utf-8"))
    db_url = os.environ.get("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    if not db_url:
        sys.exit("DATABASE_URL is not set.")

    conn = await asyncpg.connect(dsn=db_url)
    try:
        async with conn.transaction():
            for c in data["concepts"]:
                await conn.execute(
                    """
                    INSERT INTO curriculum_concepts (name, display_name, difficulty, summary, source_files)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (name) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        difficulty   = EXCLUDED.difficulty,
                        source_files = EXCLUDED.source_files
                    """,
                    c["name"], c["display_name"], c["difficulty"],
                    c.get("summary"), c.get("source_files", []),
                )
            for e in data["edges"]:
                await conn.execute(
                    """
                    INSERT INTO curriculum_edges (prerequisite, concept, confidence, evidence)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (prerequisite, concept) DO UPDATE SET
                        confidence = GREATEST(curriculum_edges.confidence, EXCLUDED.confidence),
                        evidence   = EXCLUDED.evidence
                    """,
                    e["prerequisite"], e["concept"], e["confidence"], e.get("evidence"),
                )
        roots = await conn.fetchval("SELECT COUNT(*) FROM curriculum_roots")
    finally:
        await conn.close()

    print(f"Loaded {len(data['concepts'])} concepts and {len(data['edges'])} edges.")
    print(f"{roots} root concepts (no prerequisites).")
    if roots == 0:
        print("WARNING: zero roots means every concept requires another, "
              "which indicates a cycle survived the build.")
    return 0


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Build the curriculum prerequisite DAG.")
    parser.add_argument("--out", default="data/baselines/curriculum.json")
    parser.add_argument("--limit", type=int, help="only read the first N documents")
    parser.add_argument("--load", metavar="JSON", help="load a built file into the database")
    args = parser.parse_args()

    if args.load:
        return asyncio.run(load(Path(args.load)))

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit(
            "GEMINI_API_KEY is not set.\n"
            "Building the curriculum is a one-time pass over the structured "
            "documents. Expect a few hundred model calls."
        )

    data = asyncio.run(build(args.limit, api_key))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nWritten to {out}")
    print("Review it, then load with:")
    print(f"  python scripts/build_curriculum.py --load {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
