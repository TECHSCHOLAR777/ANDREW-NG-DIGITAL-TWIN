"""
scripts/eval/persona_eval.py
─────────────────────────────────────────────────────────────────────────────
Score generated answers on two layers.

  MECHANICAL   the rules in services/persona.py: banned openers, banned
               phrases, rendered lists, headings, unfinished sentences.
               Objective, cheap, and the thing that regresses first.

  STYLISTIC    distance from the real corpus, using the baseline built by
               corpus_style.py. Sentence length, connective habits, hedging
               and pronoun balance. This is what turns "sounds like Andrew"
               into a number that can move in a direction.

The second layer is the unusual one, and it is only possible because the
source material is sitting in data/cleaned. Most persona projects assert
fidelity; this one can measure it against the person.

Two modes:

  --offline FILE   score answers already collected in a JSONL file, no API
                   key needed. Useful in CI and for scoring a transcript.
  (default)        generate answers for the question set through the live
                   pipeline, then score them. Needs GEMINI_API_KEY and a
                   reachable database.

Usage:
    python scripts/eval/persona_eval.py --offline samples.jsonl
    python scripts/eval/persona_eval.py --questions 20
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

from eval.corpus_style import analyse  # noqa: E402

BASELINE_PATH = _ROOT / "docs" / "audit" / "baselines" / "corpus_style.json"

# A fixed question set, so violation rate is comparable across prompt changes.
# Spread deliberately across the turn kinds services/routing.py distinguishes,
# because a persona can hold up on concept questions and fall apart on小 talk.
QUESTION_SET = [
    # concept
    "What is gradient descent?",
    "Explain backpropagation to me.",
    "What is the bias variance tradeoff?",
    "How does regularisation prevent overfitting?",
    "What actually happens inside an attention layer?",
    "Why do we need activation functions at all?",
    "What is the difference between L1 and L2 regularisation?",
    "How should I think about learning rate selection?",
    # opinion and strategy
    "What do you think about the future of AI?",
    "Should I learn PyTorch or TensorFlow?",
    "Is a PhD worth it for a machine learning career?",
    "How do you decide whether a problem is worth solving with AI?",
    # beginner framing
    "I am completely new to this. Where do I start?",
    "Can you explain neural networks like I am twelve?",
    # out of domain, to test the boundary behaviour
    "What is your favourite recipe for pasta?",
    "Who is going to win the football this season?",
    # greeting and small talk
    "Hi!",
    "Thanks, that helped a lot.",
    # follow-up shapes
    "Why?",
    "Can you go deeper on that last point?",
]


def load_baseline() -> dict | None:
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def style_distance(sample_stats: dict, baseline: dict) -> dict:
    """
    Compare one set of generated answers against the corpus.

    Reported as signed relative differences rather than a single score, because
    a single number hides direction: "too long and too impersonal" and "too
    short and too chatty" would otherwise look identical.
    """
    ref = baseline["overall"]

    def rel(key: str) -> float:
        base = ref.get(key, 0.0)
        if not base:
            return 0.0
        return round((sample_stats[key] - base) / base, 3)

    connective_delta = {}
    for phrase, base_rate in ref["connectives"].items():
        got = sample_stats["connectives"].get(phrase, 0.0)
        if base_rate >= 0.1:   # ignore phrases too rare to be a signal
            connective_delta[phrase] = round((got - base_rate) / base_rate, 2)

    return {
        "sentence_len_mean": {
            "corpus": ref["sentence_len_mean"],
            "generated": sample_stats["sentence_len_mean"],
            "relative": rel("sentence_len_mean"),
        },
        "pronoun_i_per_1k": {
            "corpus": ref["pronoun_i_per_1k"],
            "generated": sample_stats["pronoun_i_per_1k"],
            "relative": rel("pronoun_i_per_1k"),
        },
        "pronoun_you_per_1k": {
            "corpus": ref["pronoun_you_per_1k"],
            "generated": sample_stats["pronoun_you_per_1k"],
            "relative": rel("pronoun_you_per_1k"),
        },
        "hedges_per_1k": {
            "corpus": ref["hedges_per_1k"],
            "generated": sample_stats["hedges_per_1k"],
            "relative": rel("hedges_per_1k"),
        },
        "connectives_relative": connective_delta,
    }


def score_answers(answers: list[dict]) -> dict:
    """
    answers: [{"question": str, "answer": str}, ...]
    """
    from app.services import persona  # imported late so --help works anywhere

    total = len(answers)
    violations_by_rule: dict[str, int] = {}
    clean = 0
    per_answer = []

    for item in answers:
        found = persona.validate_response(item.get("answer", ""))
        if not found:
            clean += 1
        for v in found:
            violations_by_rule[v.rule] = violations_by_rule.get(v.rule, 0) + 1
        per_answer.append({
            "question": item.get("question", "")[:80],
            "violations": [v.rule for v in found],
            "words": len(item.get("answer", "").split()),
        })

    joined = "\n\n".join(a.get("answer", "") for a in answers)
    sample_stats = analyse(joined) if joined.strip() else None

    result = {
        "answers": total,
        "clean": clean,
        "clean_rate": round(clean / total, 3) if total else 0.0,
        "violations_by_rule": dict(sorted(
            violations_by_rule.items(), key=lambda kv: kv[1], reverse=True
        )),
        "mean_words": round(
            statistics.mean([a["words"] for a in per_answer]), 1
        ) if per_answer else 0,
        "per_answer": per_answer,
    }

    baseline = load_baseline()
    if sample_stats and baseline:
        result["style"] = style_distance(sample_stats, baseline)
    elif not baseline:
        result["style_note"] = (
            "No corpus baseline found. Run: python scripts/eval/corpus_style.py "
            "--save data/baselines/corpus_style.json"
        )

    return result


async def _generate_answers(questions: list[str]) -> list[dict]:
    """Run questions through the real generation path."""
    import asyncpg
    from dotenv import load_dotenv
    load_dotenv()

    from app.services.prompt_cache import CachedGenerationRequest, PromptCacheManager
    from app.services import graph_memory as gmem, retrieval as rtv, routing, persona

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        sys.exit("GEMINI_API_KEY is not set. Needed to generate answers.")

    db_url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not db_url:
        sys.exit("DATABASE_URL is not set.")

    pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=3)
    manager = PromptCacheManager(key)
    out: list[dict] = []

    try:
        for i, q in enumerate(questions, 1):
            print(f"  [{i}/{len(questions)}] {q[:60]}", flush=True)
            plan = routing.classify_turn(q, has_history=False)
            if plan.retrieve:
                result, _ = await rtv.retrieve_context(
                    db=pool, caller_tenant_id=None, message=q,
                    turn_history=[], gemini_key=key, top_k=plan.top_k,
                )
                knowledge = rtv.build_knowledge_block(result)
            else:
                knowledge = ""

            request = CachedGenerationRequest(
                session_id="persona-eval",
                user_message=q,
                turn_history=[],
                graph_context="No prior knowledge graph data available.",
                knowledge_block=knowledge,
                learner_profile=persona.build_learner_profile([]),
                turn_kind=plan.kind,
                temperature=0.2,
            )
            text, _status = await manager.generate(request, key)
            out.append({"question": q, "answer": text, "turn_kind": plan.kind})
    finally:
        await pool.close()

    return out


def _print_report(result: dict) -> None:
    print("\n" + "=" * 66)
    print("PERSONA EVALUATION")
    print("=" * 66)
    print(f"\n{result['answers']} answers, {result['clean']} clean "
          f"({result['clean_rate']:.0%}), mean length {result['mean_words']} words\n")

    if result["violations_by_rule"]:
        print("Violations by rule")
        for rule, count in result["violations_by_rule"].items():
            print(f"  {rule:<20} {count}")
    else:
        print("No mechanical violations.")

    style = result.get("style")
    if style:
        print("\nStyle vs corpus (relative difference, 0.0 means on target)")
        for key in ("sentence_len_mean", "pronoun_i_per_1k",
                    "pronoun_you_per_1k", "hedges_per_1k"):
            s = style[key]
            arrow = "high" if s["relative"] > 0.25 else "low" if s["relative"] < -0.25 else "ok"
            print(f"  {key:<22} corpus={s['corpus']:<8} "
                  f"generated={s['generated']:<8} {s['relative']:+.2f}  {arrow}")

        drift = {k: v for k, v in style["connectives_relative"].items() if abs(v) > 0.5}
        if drift:
            print("\n  Connective drift over 50%:")
            for phrase, delta in sorted(drift.items(), key=lambda kv: abs(kv[1]), reverse=True):
                print(f"    {phrase:<16} {delta:+.2f}")
    elif result.get("style_note"):
        print(f"\n{result['style_note']}")

    offenders = [a for a in result["per_answer"] if a["violations"]]
    if offenders:
        print("\nAnswers with violations")
        for a in offenders[:10]:
            print(f"  {', '.join(a['violations']):<28} {a['question']}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate persona fidelity.")
    parser.add_argument("--offline", metavar="JSONL",
                        help="score pre-collected answers; no API key needed")
    parser.add_argument("--questions", type=int, default=len(QUESTION_SET),
                        help="how many of the fixed question set to run")
    parser.add_argument("--save", metavar="PATH", help="write the full result as JSON")
    args = parser.parse_args()

    if args.offline:
        path = Path(args.offline)
        if not path.exists():
            sys.exit(f"No such file: {path}")
        answers = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        import asyncio
        questions = QUESTION_SET[: args.questions]
        print(f"Generating {len(questions)} answers through the live pipeline...")
        answers = asyncio.run(_generate_answers(questions))

    result = score_answers(answers)
    _print_report(result)

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Saved to {out}\n")

    # Non-zero exit when the mechanical rules regress, so CI can gate on it.
    return 0 if result["clean_rate"] >= 0.9 else 1


if __name__ == "__main__":
    sys.exit(main())
