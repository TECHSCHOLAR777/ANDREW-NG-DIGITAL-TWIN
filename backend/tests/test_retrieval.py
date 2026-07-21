"""
Tests for services/retrieval.py pure logic.

Deliberately covers only the parts that need no database and no API key:
passage merging, the query-rewrite gate, confidence scoring and prompt block
construction. Those are where the reasoning lives and where regressions would
be silent in production.

Run with either:
    python backend/tests/test_retrieval.py
    pytest backend/tests/test_retrieval.py
"""

import sys
import types
from pathlib import Path

# Stub sentence-transformers so importing the module does not pull ~420MB of
# torch weights into a unit test run.
if "sentence_transformers" not in sys.modules:
    _stub = types.ModuleType("sentence_transformers")
    _stub.SentenceTransformer = object
    sys.modules["sentence_transformers"] = _stub

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import retrieval as r  # noqa: E402


def _row(cid, source_file, idx, text, final=0.0, vec=0.0, stype="lecture"):
    return {
        "chunk_id": cid, "source_file": source_file, "chunk_index": idx,
        "chunk_text": text, "final_score": final, "vector_score": vec,
        "source_type": stype,
    }


def test_adjacent_hits_merge_into_one_passage_without_duplication():
    """Hits at 12 and 14 with window=1 must yield one passage 11-15,
    containing chunk 13 exactly once rather than two overlapping windows."""
    ranked = [
        _row("a", "cs229.txt", 12, "twelve", 0.9, 0.7),
        _row("b", "cs229.txt", 14, "fourteen", 0.5, 0.4),
    ]
    neighbors = [
        _row("x", "cs229.txt", 11, "eleven"),
        _row("a", "cs229.txt", 12, "twelve"),
        _row("y", "cs229.txt", 13, "thirteen"),
        _row("b", "cs229.txt", 14, "fourteen"),
        _row("z", "cs229.txt", 15, "fifteen"),
    ]
    passages = r.merge_into_passages(ranked, neighbors)
    assert len(passages) == 1
    assert (passages[0].start_index, passages[0].end_index) == (11, 15)
    assert passages[0].text.count("thirteen") == 1
    assert sorted(passages[0].hit_ids) == ["a", "b"]


def test_distant_hits_stay_separate_and_sort_by_best_score():
    ranked = [
        _row("a", "f.txt", 2, "two", 0.3, 0.3),
        _row("b", "f.txt", 50, "fifty", 0.9, 0.8),
    ]
    neighbors = [_row("a", "f.txt", 2, "two"), _row("b", "f.txt", 50, "fifty")]
    passages = r.merge_into_passages(ranked, neighbors)
    assert len(passages) == 2
    assert passages[0].top_score == 0.9  # best passage first


def test_passages_from_different_files_do_not_merge():
    ranked = [_row("a", "one.txt", 5, "x", 0.9, 0.7), _row("b", "two.txt", 6, "y", 0.8, 0.6)]
    neighbors = [_row("a", "one.txt", 5, "x"), _row("b", "two.txt", 6, "y")]
    assert len(r.merge_into_passages(ranked, neighbors)) == 2


def test_confidence_gates_grounding():
    assert r.score_confidence([]) == (0.0, False)
    _, weak = r.score_confidence([_row("a", "f", 1, "t", 0.1, 0.10)])
    _, strong = r.score_confidence([_row("a", "f", 1, "t", 0.1, 0.62)])
    assert weak is False
    assert strong is True


def test_rewrite_fires_on_dependent_messages():
    history = [
        {"role": "user", "content": "explain backprop"},
        {"role": "assistant", "content": "..."},
    ]
    for msg in [
        "why?", "go on", "explain more", "what about that step?",
        "can you elaborate on that", "so how does that actually work in practice",
        "and the second one?",
    ]:
        assert r.needs_rewrite(msg, history) is True, msg


def test_rewrite_skips_standalone_questions():
    """Regression guard: an opener word alone must not trigger a rewrite.
    'What is the bias variance tradeoff...' is standalone despite starting
    with 'what', and rewriting it costs latency for no benefit."""
    history = [
        {"role": "user", "content": "explain backprop"},
        {"role": "assistant", "content": "..."},
    ]
    for msg in [
        "What is the bias variance tradeoff in linear regression models?",
        "Explain how gradient descent converges on convex cost functions",
        "Give me a worked example of backpropagation through a two layer network",
    ]:
        assert r.needs_rewrite(msg, history) is False, msg


def test_rewrite_never_fires_without_history():
    assert r.needs_rewrite("why?", []) is False


def test_knowledge_block_distinguishes_empty_weak_and_strong():
    empty = r.RetrievalResult([], [], 0.1, False, "q", False)
    assert "no relevant material" in r.build_knowledge_block(empty)

    passage = r.Passage("cs229.txt", "lecture", 1, 2, "body", ["a"], 0.9)
    weak = r.RetrievalResult([passage], [], 0.2, False, "q", False)
    assert "WEAK MATCH" in r.build_knowledge_block(weak)

    strong = r.RetrievalResult([passage], [], 0.7, True, "q", False)
    block = r.build_knowledge_block(strong)
    assert "WEAK MATCH" not in block
    assert "chunks 1-2" in block


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
