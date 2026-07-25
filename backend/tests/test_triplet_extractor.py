"""
Tests for the triplet extractor's closed-world validation.

The extractor's predicate/node-type sets are a contract shared with migration
015 and the frontend TripletRow union. These tests pin the general-context
additions and confirm validation still rejects out-of-world predicates, so the
three layers cannot silently drift apart.

_validate_triplets is a pure function of its input and the module-level sets;
it needs no database or Gemini call, so the extractor is constructed with a
None pool and an empty key purely to reach the method.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.triplet_extractor import (  # noqa: E402
    TripletExtractor,
    RawTriplet,
    VALID_PREDICATES,
    VALID_NODE_TYPES,
    STUDENT_SUBJECT_PREDICATES,
)


def _extractor() -> TripletExtractor:
    return TripletExtractor(db_pool=None, gemini_api_key="")  # type: ignore[arg-type]


def _raw(predicate: str, subj_type: str = "Student", obj_type: str = "Concept") -> RawTriplet:
    return RawTriplet(
        subject="I",
        subject_type=subj_type,
        predicate=predicate,
        object="thing",
        object_type=obj_type,
        canonical_subj="Student",
        canonical_obj="Thing",
        evidence="I said so",
        confidence=0.9,
    )


def test_general_context_predicates_are_valid():
    for p in (
        "works_at", "leads", "researches", "building", "interested_in",
        "prefers", "decided", "concerned_about", "discussed", "collaborates_on",
    ):
        assert p in VALID_PREDICATES, p


def test_personal_context_predicates_are_anchored_to_student():
    for predicate in (
        "works_at", "leads", "researches", "building", "interested_in",
        "prefers", "decided", "concerned_about", "discussed", "collaborates_on",
    ):
        assert predicate in STUDENT_SUBJECT_PREDICATES, predicate


def test_educational_predicates_are_preserved():
    for p in ("struggles_with", "mastered", "curious_about", "has_prerequisite"):
        assert p in VALID_PREDICATES, p


def test_general_context_node_types_are_valid():
    for t in ("Person", "Organization", "Industry", "Goal", "Preference", "ResearchArea"):
        assert t in VALID_NODE_TYPES, t
    # Legacy types preserved (backward compatibility with existing rows).
    for t in ("Student", "Concept", "Project", "Tool", "Paper"):
        assert t in VALID_NODE_TYPES, t


def test_validate_accepts_new_predicate_and_type():
    ex = _extractor()
    kept = ex._validate_triplets([_raw("works_at", obj_type="Organization")])
    assert len(kept) == 1
    assert kept[0].predicate == "works_at"
    assert kept[0].object_type == "Organization"


def test_validate_rejects_unknown_predicate():
    ex = _extractor()
    assert ex._validate_triplets([_raw("secretly_believes")]) == []


def test_validate_normalizes_unknown_node_type_to_concept():
    ex = _extractor()
    kept = ex._validate_triplets([_raw("curious_about", obj_type="Nonsense")])
    assert len(kept) == 1
    assert kept[0].object_type == "Concept"


def test_validate_repairs_malformed_organization_self_loop():
    ex = _extractor()
    triplet = _raw("works_at", subj_type="Organization", obj_type="Organization")
    triplet.subject = "AIMS-DTU"
    triplet.canonical_subj = "AIMS-DTU"
    triplet.object = "AIMS-DTU"
    triplet.canonical_obj = "AIMS-DTU"

    kept = ex._validate_triplets([triplet])

    assert len(kept) == 1
    assert kept[0].subject == "I"
    assert kept[0].canonical_subj == "Student"
    assert kept[0].subject_type == "Student"
    assert kept[0].canonical_obj == "AIMS-DTU"


def test_validate_rejects_true_concept_self_loop():
    ex = _extractor()
    triplet = _raw("related_to", subj_type="Concept", obj_type="Concept")
    triplet.subject = "Cybersecurity"
    triplet.canonical_subj = "Cybersecurity"
    triplet.object = "cybersecurity"
    triplet.canonical_obj = "cybersecurity"

    assert ex._validate_triplets([triplet]) == []


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
