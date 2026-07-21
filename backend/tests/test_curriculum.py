"""
Tests for services/curriculum.py.

The gap diagnosis is the project's most distinctive claim, so it gets the most
scrutiny here. "Three separate confusions share one upstream cause" is either
correct or it is a confidently wrong statement to a student, and there is no
middle ground.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.curriculum import (  # noqa: E402
    LearnerState,
    diagnose_gaps,
    learning_path,
    normalise,
    retrieval_hints,
    topological_order,
)

# A small slice of a real ML curriculum.
#   derivatives -> chain rule -> backpropagation
#   derivatives -> gradient descent -> adam
#   linear algebra -> neural networks -> backpropagation
PREREQS = {
    "chain rule": {"derivatives"},
    "backpropagation": {"chain rule", "neural networks"},
    "gradient descent": {"derivatives"},
    "adam": {"gradient descent"},
    "neural networks": {"linear algebra"},
    "attention": {"neural networks", "softmax"},
    "transformers": {"attention", "backpropagation"},
}


def test_normalise_matches_the_sql_definition():
    assert normalise("Neural Networks") == "neural networks"
    assert normalise("  Chain-Rule  ") == "chain rule"
    assert normalise("L2 Regularisation!") == "l2 regularisation"
    assert normalise("") == ""
    assert normalise(None) == ""


def test_topological_order_puts_prerequisites_first():
    order = topological_order({"backpropagation"}, PREREQS)
    assert order.index("derivatives") < order.index("chain rule")
    assert order.index("chain rule") < order.index("backpropagation")
    assert order.index("linear algebra") < order.index("neural networks")
    assert order.index("neural networks") < order.index("backpropagation")


def test_topological_order_only_walks_the_relevant_subgraph():
    """Asking for backpropagation must not drag in Adam, which is unrelated
    to it despite sharing an ancestor."""
    order = topological_order({"backpropagation"}, PREREQS)
    assert "adam" not in order
    assert "gradient descent" not in order


def test_cycles_do_not_lose_concepts():
    """A cycle is a data quality problem in the extracted DAG. Hiding concepts
    from a learner because of it would be the wrong response."""
    cyclic = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
    order = topological_order({"a"}, cyclic)
    assert set(order) == {"a", "b", "c"}


def test_learning_path_skips_what_is_already_known():
    beginner = LearnerState()
    advanced = LearnerState(mastered={"derivatives", "chain rule", "linear algebra"})

    long_path = learning_path("backpropagation", beginner, PREREQS)
    short_path = learning_path("backpropagation", advanced, PREREQS)

    assert len(short_path) < len(long_path)
    assert "derivatives" not in short_path
    assert "chain rule" not in short_path
    assert "backpropagation" in short_path


def test_learning_path_ends_at_the_target():
    path = learning_path("transformers", LearnerState(), PREREQS)
    assert path[-1] == "transformers"


def test_diagnose_gaps_finds_the_shared_root_cause():
    """The headline behaviour. A student stuck on backpropagation, gradient
    descent and Adam does not have three problems; they have one, and it is
    derivatives."""
    state = LearnerState(struggling={"backpropagation", "gradient descent", "adam"})
    gaps = diagnose_gaps(state, PREREQS)

    assert gaps, "no shared prerequisite found"
    root, explains = gaps[0]
    assert root == "derivatives"
    assert "backpropagation" in explains
    assert "gradient descent" in explains


def test_diagnose_gaps_ignores_prerequisites_already_mastered():
    state = LearnerState(
        struggling={"backpropagation", "gradient descent", "adam"},
        mastered={"derivatives"},
    )
    roots = [g[0] for g in diagnose_gaps(state, PREREQS)]
    assert "derivatives" not in roots


def test_diagnose_gaps_does_not_report_a_symptom_as_the_cause():
    """Gradient descent is upstream of Adam, but the student is explicitly
    stuck on it too, which makes it another symptom rather than the cause."""
    state = LearnerState(struggling={"adam", "gradient descent"})
    roots = [g[0] for g in diagnose_gaps(state, PREREQS)]
    assert "gradient descent" not in roots


def test_diagnose_gaps_stays_quiet_on_a_single_struggle():
    """One confusion is not evidence of a systemic gap, and guessing at one
    would be worse than saying nothing."""
    state = LearnerState(struggling={"backpropagation"})
    assert diagnose_gaps(state, PREREQS) == []


def test_retrieval_hints_expand_unmastered_prerequisites():
    """Retrieval conditioned on learner state: the question is about
    backpropagation, the student is shaky on the chain rule, so the retriever
    is told to fetch chain rule material the question never mentioned."""
    state = LearnerState(struggling={"chain rule"})
    hints = retrieval_hints({"backpropagation"}, state, PREREQS)
    assert "chain rule" in hints["expand"]


def test_retrieval_hints_do_not_expand_mastered_prerequisites():
    state = LearnerState(mastered={"chain rule", "neural networks"})
    hints = retrieval_hints({"backpropagation"}, state, PREREQS)
    assert "chain rule" not in hints["expand"]
    assert "neural networks" not in hints["expand"]


def test_retrieval_hints_suppress_settled_ground():
    state = LearnerState(mastered={"linear algebra"})
    hints = retrieval_hints({"backpropagation"}, state, PREREQS)
    assert "linear algebra" in hints["suppress"]


def test_learner_state_resolves_contradictions_defensively():
    """Extraction should already have retired one side via the temporal graph,
    but a read path must not depend on that having worked."""
    state = LearnerState.from_edges([
        {"predicate": "mastered", "object": "Backpropagation"},
        {"predicate": "struggles_with", "object": "Backpropagation"},
    ])
    assert "backpropagation" in state.struggling
    assert "backpropagation" not in state.mastered


def test_learner_state_normalises_incoming_names():
    state = LearnerState.from_edges([
        {"predicate": "mastered", "object": "Neural Networks"},
        {"predicate": "curious_about", "object": "  Chain-Rule "},
    ])
    assert state.mastered == {"neural networks"}
    assert state.curious == {"chain rule"}


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
