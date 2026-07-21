"""
scripts/eval/corpus_style.py
─────────────────────────────────────────────────────────────────────────────
Measure the style of the real corpus, to serve as the reference the twin is
compared against.

WHY THIS EXISTS
───────────────
Persona fidelity was previously a matter of opinion. Someone reads an answer,
decides it "sounds like Andrew", and that is the whole evaluation. So no prompt
change can be judged, and a regression is invisible until someone happens to
notice.

Most persona projects cannot do better than that, because they have nothing to
compare against. This one can: the corpus IS the reference. Sentence length,
connective habits, hedging frequency and pronoun balance are all measurable on
the source material, and then measurable again on generated answers.

That turns "sounds like him" into a number with a target.

A second, cheaper payoff: this validates the persona's own rules. The prompt
bans phrases like "Great question". If Andrew actually says them regularly in
transcripts, the ban is wrong and this will show it.

Runs offline. No API key, no database.

Usage:
    python scripts/eval/corpus_style.py
    python scripts/eval/corpus_style.py --save baselines/corpus_style.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "backend"))

CORPUS_DIR = _ROOT / "data" / "cleaned"

# Andrew's characteristic connectives, from the persona prompt. Measuring them
# is how we find out whether the prompt's claims match the source.
CONNECTIVES = [
    "so", "okay", "alright", "actually", "right", "i think", "i believe",
    "you know", "let's say", "in other words", "it turns out",
]

HEDGES = [
    "i think", "i believe", "pretty", "a lot of", "roughly", "kind of",
    "sort of", "probably", "maybe", "i'd say", "tends to", "one of the patterns",
]

# From services/persona.py. If these appear often in the real corpus, the
# persona is banning something the man actually says.
BANNED_PROBES = [
    "great question", "excellent question", "good question",
    "does that make sense", "let's dive in", "let's break this down",
    "absolutely!", "certainly!", "in conclusion",
]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z']+")
_METADATA_LINE = re.compile(
    r"^\s*#?\s*(title|url|date|domain|author|source|extracted|scraped|"
    r"published|updated|link|category|tags?)\s*:",
    re.IGNORECASE,
)


def _classify(path: Path) -> str:
    """Spoken and written Andrew differ enough that averaging them hides both."""
    parent = path.parent.name
    if parent == "transcripts":
        return "spoken"
    if parent == "the_batch":
        return "newsletter"
    if parent == "blog_posts":
        return "blog"
    return "written"


def _strip_metadata(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not _METADATA_LINE.match(line)
    )


def _phrase_rate(text_lower: str, phrase: str, words: int) -> float:
    """Occurrences per 1000 words, so documents of different length compare."""
    if words == 0:
        return 0.0
    pattern = r"\b" + re.escape(phrase).replace(r"\ ", r"\s+")
    return 1000.0 * len(re.findall(pattern, text_lower)) / words


def analyse(text: str) -> dict:
    """Style statistics for one body of text."""
    clean = _strip_metadata(text)
    words = _WORD.findall(clean)
    n_words = len(words)
    lowered = clean.lower()

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(clean) if s.strip()]
    lengths = [len(_WORD.findall(s)) for s in sentences]
    lengths = [n for n in lengths if n > 0]

    if not lengths:
        lengths = [0]

    lower_words = [w.lower() for w in words]
    counts = Counter(lower_words)

    return {
        "words": n_words,
        "sentences": len(sentences),
        "sentence_len_mean": round(statistics.mean(lengths), 2),
        "sentence_len_median": round(statistics.median(lengths), 2),
        "sentence_len_p90": round(
            statistics.quantiles(lengths, n=10)[-1] if len(lengths) > 9 else max(lengths), 2
        ),
        "pronoun_i_per_1k": round(1000 * counts.get("i", 0) / max(n_words, 1), 2),
        "pronoun_you_per_1k": round(1000 * counts.get("you", 0) / max(n_words, 1), 2),
        "pronoun_we_per_1k": round(1000 * counts.get("we", 0) / max(n_words, 1), 2),
        "connectives": {
            c: round(_phrase_rate(lowered, c, n_words), 3) for c in CONNECTIVES
        },
        "hedges_per_1k": round(
            sum(_phrase_rate(lowered, h, n_words) for h in HEDGES), 3
        ),
        "banned_probes": {
            b: round(_phrase_rate(lowered, b, n_words), 4) for b in BANNED_PROBES
        },
    }


def _merge(stats: list[dict]) -> dict:
    """Aggregate per-document statistics, weighting by word count."""
    if not stats:
        return {}
    total_words = sum(s["words"] for s in stats) or 1

    def weighted(key: str) -> float:
        return round(sum(s[key] * s["words"] for s in stats) / total_words, 2)

    def weighted_nested(group: str, key: str) -> float:
        return round(
            sum(s[group][key] * s["words"] for s in stats) / total_words, 3
        )

    return {
        "documents": len(stats),
        "words": total_words,
        "sentences": sum(s["sentences"] for s in stats),
        "sentence_len_mean": weighted("sentence_len_mean"),
        "sentence_len_median": weighted("sentence_len_median"),
        "sentence_len_p90": weighted("sentence_len_p90"),
        "pronoun_i_per_1k": weighted("pronoun_i_per_1k"),
        "pronoun_you_per_1k": weighted("pronoun_you_per_1k"),
        "pronoun_we_per_1k": weighted("pronoun_we_per_1k"),
        "hedges_per_1k": weighted("hedges_per_1k"),
        "connectives": {c: weighted_nested("connectives", c) for c in CONNECTIVES},
        "banned_probes": {b: weighted_nested("banned_probes", b) for b in BANNED_PROBES},
    }


def build_baseline(limit: int | None = None) -> dict:
    if not CORPUS_DIR.is_dir():
        sys.exit(f"No corpus at {CORPUS_DIR}. Run the collectors first.")

    files = sorted(CORPUS_DIR.glob("**/*.txt"))
    if limit:
        files = files[:limit]
    if not files:
        sys.exit(f"No .txt files under {CORPUS_DIR}")

    by_kind: dict[str, list[dict]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore").replace("\x00", "")
        if not text.strip():
            continue
        by_kind.setdefault(_classify(path), []).append(analyse(text))

    return {
        "overall": _merge([s for group in by_kind.values() for s in group]),
        "by_kind": {kind: _merge(group) for kind, group in sorted(by_kind.items())},
    }


def _print_report(baseline: dict) -> None:
    overall = baseline["overall"]
    print("\n" + "=" * 66)
    print("CORPUS STYLE BASELINE")
    print("=" * 66)
    print(f"\n{overall['documents']} documents, {overall['words']:,} words, "
          f"{overall['sentences']:,} sentences\n")

    print("Sentence length (words)")
    print(f"  mean {overall['sentence_len_mean']}   "
          f"median {overall['sentence_len_median']}   "
          f"p90 {overall['sentence_len_p90']}")
    print("  The persona asks for sentences 'rarely more than about twenty "
          "words' in teaching mode.\n")

    print("Pronouns per 1000 words")
    print(f"  I {overall['pronoun_i_per_1k']}   "
          f"you {overall['pronoun_you_per_1k']}   "
          f"we {overall['pronoun_we_per_1k']}\n")

    print(f"Hedging per 1000 words: {overall['hedges_per_1k']}\n")

    print("Connectives per 1000 words (top 8)")
    for phrase, rate in sorted(
        overall["connectives"].items(), key=lambda kv: kv[1], reverse=True
    )[:8]:
        print(f"  {phrase:<18} {rate}")

    print("\nBanned-phrase probe (does the real corpus contain what the persona bans?)")
    flagged = False
    for phrase, rate in sorted(
        overall["banned_probes"].items(), key=lambda kv: kv[1], reverse=True
    ):
        if rate > 0:
            flagged = True
            print(f"  {phrase:<26} {rate} per 1k words")
    if not flagged:
        print("  none present. The persona's bans do not contradict the source.")

    print("\nBy source kind")
    for kind, s in baseline["by_kind"].items():
        if not s:
            continue
        print(f"  {kind:<11} docs={s['documents']:<5} "
              f"sent_len={s['sentence_len_mean']:<6} "
              f"I/1k={s['pronoun_i_per_1k']:<6} hedge/1k={s['hedges_per_1k']}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure corpus writing style.")
    parser.add_argument("--save", metavar="PATH", help="write the baseline as JSON")
    parser.add_argument("--limit", type=int, help="only read the first N files")
    args = parser.parse_args()

    baseline = build_baseline(limit=args.limit)
    _print_report(baseline)

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        print(f"Baseline written to {out}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
