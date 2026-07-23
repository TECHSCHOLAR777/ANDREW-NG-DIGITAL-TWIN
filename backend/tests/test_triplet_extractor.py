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
