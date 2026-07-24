"""
scripts/eval/golden_set.py
─────────────────────────────────────────────────────────────────────────────
Build a question-to-passage golden set for retrieval evaluation.

DESIGN DECISIONS WORTH KNOWING
──────────────────────────────
1. Built from the LOCAL corpus, not the database.
   Chunks are produced here with the same scripts/chunking.py the ingest uses,
   so no database is required to build a golden set. That matters because the
   set should survive a re-ingest.

2. Labelled by (source_file, chunk_index), not by chunk UUID.
   UUIDs are regenerated on every ingest, so a UUID-labelled golden set dies
   the first time the corpus is rebuilt. The file-and-index pair is stable as
   long as the chunker is.

3. Questions are paraphrased on purpose.
   The obvious way to generate a question from a passage produces one that
   quotes the passage, which retrieval then solves by lexical overlap alone.
   That measures nothing. The prompt below explicitly demands the question
   avoid distinctive wording from the source, so a hit means the retriever
   understood rather than string-matched.

4. Negatives are included.
   A retrieval set made only of answerable questions cannot tell you whether
   abstention works. RETRIEVAL_MIN_COSINE was picked by intuition at 0.35;
   negatives are how that number gets calibrated instead of guessed.

Usage:
    python scripts/eval/golden_set.py --n 100 --out data/baselines/golden_set.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "backend"))

CORPUS_DIR = _ROOT / "data" / "cleaned"

QUESTION_PROMPT = """You are building an evaluation set for a document search system.

Given a passage from Andrew Ng's teaching material, write ONE question that the
passage answers.

Hard requirements:
- The question must be answerable from this passage alone.
- AVOID reusing distinctive phrases from the passage. Paraphrase the concept.
  If the passage says "the parameters theta are updated by the learning rate",
  do NOT ask "how are the parameters theta updated by the learning rate".
  Ask something like "how does the algorithm decide how far to move each step".
- Write it the way a student would actually ask, not like an exam question.
- One sentence. No preamble. Return ONLY the question.

Passage:
---
{passage}
---

Question:"""

NEGATIVE_PROMPT = """Write {n} questions that a student might plausibly ask a machine
learning tutor, but that could NOT be answered from Andrew Ng's lectures, books
or newsletters about machine learning.

Good examples: questions about unrelated fields, about very recent events, about
personal details, or about specific competing products.

Return one question per line. No numbering, no preamble."""


def load_corpus_chunks(min_chars: int = 400) -> list[dict]:
    """Chunk the corpus exactly as ingestion does."""
    from chunking import chunk_document
    from ingest_supabase import parse_metadata_headers

    if not CORPUS_DIR.is_dir():
        sys.exit(f"No corpus at {CORPUS_DIR}")

    out: list[dict] = []
    for path in sorted(CORPUS_DIR.glob("**/*.txt")):
        raw = path.read_text(encoding="utf-8", errors="ignore").replace("\x00", "")
        meta, body = parse_metadata_headers(raw)
        title = meta.get("title") or path.stem.replace("_", " ")
        for chunk in chunk_document(body, doc_title=title):
            # Short passages make ambiguous questions, so they are poor golds.
            if len(chunk.text) >= min_chars:
                out.append({
                    "source_file": path.name,
                    "chunk_index": chunk.index,
                    "text": chunk.text,
                    "heading_trail": chunk.heading_trail,
                })
    return out


def _generate(prompt: str, api_key: str, max_tokens: int = 256) -> str:
    from app.services import gemini_client
    result = gemini_client.generate_sync(
        api_key=api_key,
        model=os.getenv("REWRITE_MODEL", "gemini-3.5-flash-lite"),
        contents=[{"role": "user", "parts": [{"text": prompt}]}],
        temperature=0.4,
        max_output_tokens=max_tokens,
        thinking_budget=0,
    )
    return (result.text or "").strip()


def _clean_question(text: str) -> str:
    text = text.strip().strip('"').strip()
    text = re.sub(r"^(question|q)\s*[:.\-]\s*", "", text, flags=re.I)
    return text.split("\n")[0].strip()


def build(n_positive: int, n_negative: int, seed: int, api_key: str) -> list[dict]:
    chunks = load_corpus_chunks()
    if not chunks:
        sys.exit("Corpus produced no chunks large enough to build questions from.")

    print(f"corpus produced {len(chunks)} candidate passages")
    random.seed(seed)
    # Prefer passages that carry a section trail: they are self-contained
    # enough that a single question can have a single right answer.
    with_trail = [c for c in chunks if len(c["heading_trail"]) > 1]
    pool = with_trail if len(with_trail) >= n_positive else chunks
    sample = random.sample(pool, min(n_positive, len(pool)))

    rows: list[dict] = []
    for i, chunk in enumerate(sample, 1):
        question = _clean_question(
            _generate(QUESTION_PROMPT.format(passage=chunk["text"][:2500]), api_key)
        )
        if not question or len(question) < 12:
            print(f"  [{i}] skipped, unusable question")
            continue
        rows.append({
            "question": question,
            "answerable": True,
            "source_file": chunk["source_file"],
            "chunk_index": chunk["chunk_index"],
            "heading_trail": chunk["heading_trail"],
        })
        print(f"  [{i}/{len(sample)}] {question[:72]}")

    if n_negative:
        print(f"\ngenerating {n_negative} unanswerable questions for abstention calibration")
        raw = _generate(NEGATIVE_PROMPT.format(n=n_negative), api_key, max_tokens=1024)
        for line in raw.splitlines():
            q = _clean_question(line)
            if len(q) > 12:
                rows.append({
                    "question": q,
                    "answerable": False,
                    "source_file": None,
                    "chunk_index": None,
                })
        print(f"  collected {sum(1 for r in rows if not r['answerable'])}")

    return rows


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Build a retrieval golden set.")
    parser.add_argument("--n", type=int, default=100, help="answerable questions")
    parser.add_argument("--negatives", type=int, default=20, help="unanswerable questions")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="data/baselines/golden_set.jsonl")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit(
            "GEMINI_API_KEY is not set.\n"
            "Building the golden set needs one model call per question. "
            "It is a one-time cost of roughly a cent for 100 questions."
        )

    rows = build(args.n, args.negatives, args.seed, api_key)
    if not rows:
        sys.exit("No questions were generated.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    answerable = sum(1 for r in rows if r["answerable"])
    print(f"\nWrote {len(rows)} questions to {out}")
    print(f"  {answerable} answerable, {len(rows) - answerable} negatives")
    print("\nNext: python scripts/eval/retrieval_eval.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
