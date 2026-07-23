"""
Tests for services/persona.py validators and services/routing.py.

These exist because the persona's mechanical rules moved out of the prompt and
into code. That trade is only worth it if the code is actually correct, and the
violation rate over a fixed question set is meant to become a tracked persona
quality metric (see scripts/eval/).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import persona, routing  # noqa: E402


# ── Validators ───────────────────────────────────────────────────────────────

def test_banned_openers_are_caught():
    for bad in [
        "Great question! Gradient descent walks downhill.",
        "That's a really thoughtful question. Let me answer.",
        "Excellent question. Here we go.",
        '"Good question" is how I would start. No wait.',
    ]:
        rules = [v.rule for v in persona.validate_response(bad)]
        assert "banned_opener" in rules, bad


def test_substantive_opening_passes():
    good = "So gradient descent walks downhill in thick fog, right?"
    assert [v.rule for v in persona.validate_response(good)] == []


def test_comprehension_check_phrases_are_caught():
    for bad in [
        "The key idea is simple. Does that make sense?",
        "That covers it. Do you follow?",
        "Here it is. Is that clear?",
    ]:
        rules = [v.rule for v in persona.validate_response(bad)]
        assert "banned_phrase" in rules, bad


def test_rendered_structure_is_caught():
    assert "markdown_header" in [v.rule for v in persona.validate_response("## Overview\nText here.")]
    assert "bullet_list" in [v.rule for v in persona.validate_response("Points:\n- first\n- second")]
    assert "numbered_list" in [v.rule for v in persona.validate_response("Steps:\n1. do this\n2. then that")]
    assert "scaffold_label" in [v.rule for v in persona.validate_response("Hook: imagine a house price.")]


def test_unfinished_response_is_an_error():
    violations = persona.validate_response("So the key idea here is that we")
    assert "unfinished" in [v.rule for v in violations]
    assert persona.has_error(violations)


def test_empty_response_is_an_error():
    assert persona.has_error(persona.validate_response(""))


def test_repair_strips_banned_opener_only():
    out = persona.repair_response("Great question! Gradient descent walks downhill.")
    assert out == "Gradient descent walks downhill."


def test_repair_leaves_clean_text_alone():
    clean = "So the key idea here is that bias and variance trade off."
    assert persona.repair_response(clean) == clean


# ── Learner profile ──────────────────────────────────────────────────────────

def test_profile_detects_business_audience():
    out = persona.build_learner_profile([{"predicate": "is", "object": "Product Manager"}])
    assert "business" in out
    assert "strategy" in out.lower()


def test_profile_detects_advanced_audience():
    out = persona.build_learner_profile([{"predicate": "is", "object": "PhD researcher"}])
    assert "advanced" in out
    assert "formalism" in out.lower()


def test_profile_for_empty_graph_is_beginner():
    assert "beginner" in persona.build_learner_profile([])


def test_profile_lists_mastered_so_they_are_not_retaught():
    out = persona.build_learner_profile([
        {"predicate": "mastered", "object": "Linear Regression"},
        {"predicate": "mastered", "object": "Gradient Descent"},
    ])
    assert "Linear Regression" in out
    assert "not re-teach" in out


def test_profile_flags_struggles_for_slower_pacing():
    out = persona.build_learner_profile([{"predicate": "struggles_with", "object": "Backpropagation"}])
    assert "Backpropagation" in out
    assert "Slow down" in out


# ── Audience profile: general (non-student) context, migration 015 ────────────

def test_profile_founder_leading_startup_reads_business():
    # A founder given only through the new professional predicates still
    # calibrates to the strategy-oriented audience.
    out = persona.build_learner_profile([
        {"predicate": "is", "object": "Founder"},
        {"predicate": "leads", "object": "an AI startup"},
    ])
    assert "business" in out
    assert "startup" in out.lower()


def test_profile_researcher_via_researches_predicate_reads_advanced():
    out = persona.build_learner_profile([
        {"predicate": "researches", "object": "Diffusion Models"},
    ])
    assert "advanced" in out
    assert "formalism" in out.lower()


def test_profile_engineer_role_reads_advanced():
    out = persona.build_learner_profile([
        {"predicate": "is", "object": "Machine Learning Engineer"},
    ])
    assert "advanced" in out


def test_profile_surfaces_professional_context():
    out = persona.build_learner_profile([
        {"predicate": "works_at", "object": "Acme Robotics"},
        {"predicate": "building", "object": "a defect-detection pipeline"},
    ])
    assert "Professional context" in out
    assert "Acme Robotics" in out


def test_profile_honours_stated_preferences():
    out = persona.build_learner_profile([
        {"predicate": "prefers", "object": "concise, code-first answers"},
    ])
    assert "Stated preferences" in out
    assert "code-first" in out


def test_profile_general_visitor_with_no_signals_is_beginner_default():
    # A general visitor whose only context is an interest still gets a safe,
    # accessible default rather than assumed expertise.
    out = persona.build_learner_profile([
        {"predicate": "interested_in", "object": "AI in healthcare"},
    ])
    assert "LEARNER PROFILE" in out
    assert "AI in healthcare" in out


# ── Routing ──────────────────────────────────────────────────────────────────

def test_greetings_skip_retrieval_and_extraction():
    for msg in ["hi", "hey", "thanks!", "ok", "good morning", "bye"]:
        plan = routing.classify_turn(msg, has_history=True)
        assert plan.kind == routing.GREETING, msg
        assert plan.retrieve is False
        assert plan.extract_triples is False


def test_concept_questions_get_full_retrieval():
    for msg in [
        "what is gradient descent?",
        "Explain how backpropagation computes gradients through a deep network",
        "derive the update rule for logistic regression",
    ]:
        plan = routing.classify_turn(msg, has_history=False)
        assert plan.kind == routing.CONCEPT, msg
        assert plan.retrieve is True
        assert plan.top_k == 10


def test_short_message_with_history_is_a_followup():
    plan = routing.classify_turn("why?", has_history=True)
    assert plan.kind == routing.FOLLOWUP
    assert plan.retrieve is True


def test_opinion_questions_are_separated_from_concepts():
    plan = routing.classify_turn("what do you think about the future of AI?", has_history=False)
    assert plan.kind == routing.OPINION
    assert plan.top_k < 10   # lighter retrieval than a concept question


def test_greeting_check_precedes_length_heuristics():
    """'thanks!' is short and would otherwise fall through to followup."""
    assert routing.classify_turn("thanks!", has_history=True).kind == routing.GREETING


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
