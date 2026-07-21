"""
scripts/eval/retrieval_eval.py
─────────────────────────────────────────────────────────────────────────────
Measure retrieval quality against the golden set.

WHAT IT REPORTS
───────────────
  recall@k    did the gold passage appear in the top k
  MRR         how high it ranked when it did appear
  abstention  can confidence separate answerable from unanswerable questions

The third one is the reason this file exists in its current shape. Every RAG
project measures recall. Almost none measure whether the system knows when it
has nothing useful, and that is exactly the failure a tutoring product cannot
afford: confidently reciting irrelevant passages is worse than saying "that is
outside what I have written about".

RETRIEVAL_MIN_COSINE was set to 0.35 by intuition and flagged at the time as
uncalibrated. With negatives in the golden set, this computes the threshold
that best separates the two populations, so the number becomes measured.

ABLATIONS
─────────
--ablate runs the same questions with neighbour expansion off and query
rewriting off, so the contribution of each is a number rather than a belief.
That matters because both were added on reasoning alone.

Requires a reachable database with the corpus ingested.

Usage:
    python scripts/eval/retrieval_eval.py
    python scripts/eval/retrieval_eval.py --ablate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

DEFAULT_GOLDEN = _ROOT / "docs" / "audit" / "baselines" / "golden_set.jsonl"


def load_golden(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(
            f"No golden set at {path}\n"
            "Build one first: python scripts/eval/golden_set.py"
        )
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rank_of_gold(rows, source_file: str, chunk_index: int) -> int | None:
    """
    Position of the gold passage in the ranked results, 1-based.

    Neighbour expansion means a hit adjacent to the gold still surfaces the
    right text, so an index within one counts. Being stricter would punish the
    system for a design choice that demonstrably helps the reader.
    """
    for i, row in enumerate(rows, 1):
        if row["source_file"] != source_file:
            continue
        if abs(int(row["chunk_index"]) - int(chunk_index)) <= 1:
            return i
    return None


async def evaluate(
    golden: list[dict],
    neighbour_window: int | None = None,
    disable_rewrite: bool = False,
) -> dict:
    import asyncpg
    from dotenv import load_dotenv
    load_dotenv()

    from app.services import retrieval as rtv

    if neighbour_window is not None:
        rtv.NEIGHBOR_WINDOW = neighbour_window
    if disable_rewrite:
        rtv.ENABLE_QUERY_REWRITE = False

    db_url = os.environ.get("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    if not db_url:
        sys.exit("DATABASE_URL is not set.")

    key = os.environ.get("GEMINI_API_KEY", "").strip()

    pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=4)
    ranks: list[int | None] = []
    pos_conf: list[float] = []
    neg_conf: list[float] = []
    misses: list[dict] = []

    try:
        for i, item in enumerate(golden, 1):
            result, _ = await rtv.retrieve_context(
                db=pool,
                caller_tenant_id=None,
                message=item["question"],
                turn_history=[],
                gemini_key=key,
                top_k=10,
            )
            rows = [
                {"source_file": r["source_file"], "chunk_index": r["chunk_index"]}
                for r in result.ranked_rows
            ]

            if item["answerable"]:
                rank = _rank_of_gold(rows, item["source_file"], item["chunk_index"])
                ranks.append(rank)
                pos_conf.append(result.confidence)
                if rank is None:
                    misses.append({
                        "question": item["question"],
                        "expected": f"{item['source_file']}#{item['chunk_index']}",
                        "confidence": round(result.confidence, 3),
                    })
            else:
                neg_conf.append(result.confidence)

            if i % 10 == 0:
                print(f"  {i}/{len(golden)}", flush=True)
    finally:
        await pool.close()

    found = [r for r in ranks if r is not None]
    n = len(ranks) or 1

    return {
        "answerable": len(ranks),
        "recall@1": round(sum(1 for r in found if r <= 1) / n, 3),
        "recall@3": round(sum(1 for r in found if r <= 3) / n, 3),
        "recall@5": round(sum(1 for r in found if r <= 5) / n, 3),
        "recall@10": round(sum(1 for r in found if r <= 10) / n, 3),
        "mrr": round(sum(1.0 / r for r in found) / n, 3),
        "median_rank_when_found": statistics.median(found) if found else None,
        "confidence_answerable_mean": round(statistics.mean(pos_conf), 3) if pos_conf else None,
        "confidence_negative_mean": round(statistics.mean(neg_conf), 3) if neg_conf else None,
        "suggested_threshold": _suggest_threshold(pos_conf, neg_conf),
        "negatives": len(neg_conf),
        "misses": misses[:15],
    }


def _suggest_threshold(pos: list[float], neg: list[float]) -> dict | None:
    """
    Find the cosine cutoff that best separates answerable from unanswerable.

    Reported with the errors it would make in both directions, because the
    right trade-off is a product decision: a tutor that abstains too readily is
    useless, one that never abstains is untrustworthy.
    """
    if not pos or not neg:
        return None

    candidates = sorted(set(round(v, 3) for v in pos + neg))
    best = None
    for t in candidates:
        true_pos = sum(1 for v in pos if v >= t)
        true_neg = sum(1 for v in neg if v < t)
        accuracy = (true_pos + true_neg) / (len(pos) + len(neg))
        if best is None or accuracy > best["accuracy"]:
            best = {
                "threshold": t,
                "accuracy": round(accuracy, 3),
                "answerable_kept": round(true_pos / len(pos), 3),
                "negatives_rejected": round(true_neg / len(neg), 3),
            }

    current = float(os.getenv("RETRIEVAL_MIN_COSINE", "0.35"))
    best["current_setting"] = current
    best["current_accuracy"] = round(
        (sum(1 for v in pos if v >= current) + sum(1 for v in neg if v < current))
        / (len(pos) + len(neg)), 3
    )
    return best


def _print_report(title: str, r: dict) -> None:
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)
    print(f"\n{r['answerable']} answerable questions, {r['negatives']} negatives\n")
    print(f"  recall@1   {r['recall@1']:.3f}")
    print(f"  recall@3   {r['recall@3']:.3f}")
    print(f"  recall@5   {r['recall@5']:.3f}")
    print(f"  recall@10  {r['recall@10']:.3f}")
    print(f"  MRR        {r['mrr']:.3f}")
    if r["median_rank_when_found"]:
        print(f"  median rank when found: {r['median_rank_when_found']}")

    if r["suggested_threshold"]:
        t = r["suggested_threshold"]
        print("\nAbstention calibration")
        print(f"  answerable questions, mean confidence: {r['confidence_answerable_mean']}")
        print(f"  negatives,             mean confidence: {r['confidence_negative_mean']}")
        print(f"  best threshold {t['threshold']} "
              f"(accuracy {t['accuracy']}, keeps {t['answerable_kept']:.0%} of "
              f"answerable, rejects {t['negatives_rejected']:.0%} of negatives)")
        print(f"  currently configured: {t['current_setting']} "
              f"(accuracy {t['current_accuracy']})")
        if abs(t["threshold"] - t["current_setting"]) > 0.03:
            print(f"  -> set RETRIEVAL_MIN_COSINE={t['threshold']}")

    if r["misses"]:
        print(f"\nMisses ({len(r['misses'])} shown)")
        for m in r["misses"][:8]:
            print(f"  conf={m['confidence']:<6} {m['question'][:60]}")
            print(f"           expected {m['expected']}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality.")
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    parser.add_argument("--ablate", action="store_true",
                        help="also run with neighbour expansion and rewriting disabled")
    parser.add_argument("--save", metavar="PATH")
    args = parser.parse_args()

    golden = load_golden(Path(args.golden))
    print(f"Loaded {len(golden)} golden questions")

    baseline = asyncio.run(evaluate(golden))
    _print_report("RETRIEVAL EVALUATION (current configuration)", baseline)
    results = {"baseline": baseline}

    if args.ablate:
        print("Ablation: neighbour expansion off")
        no_neighbours = asyncio.run(evaluate(golden, neighbour_window=0))
        _print_report("ABLATION: no neighbour expansion", no_neighbours)
        results["no_neighbours"] = no_neighbours

        print("Ablation: query rewriting off")
        no_rewrite = asyncio.run(evaluate(golden, disable_rewrite=True))
        _print_report("ABLATION: no query rewriting", no_rewrite)
        results["no_rewrite"] = no_rewrite

        print("=" * 66)
        print("ABLATION SUMMARY (change in MRR against baseline)")
        print("=" * 66)
        for name, r in results.items():
            if name == "baseline":
                continue
            delta = r["mrr"] - baseline["mrr"]
            print(f"  {name:<18} MRR {r['mrr']:.3f}  ({delta:+.3f})")
        print()

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Saved to {out}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
