"""
services/curriculum.py
─────────────────────────────────────────────────────────────────────────────
The curriculum layer: what depends on what, and where a given student is.

WHAT THIS UNLOCKS
─────────────────
Until now the graph could say "you struggle with backpropagation". It could not
say "you struggle with backpropagation because you never got the chain rule",
because it had no representation of one concept depending on another.

With a prerequisite DAG overlaid by per-student mastery, three things become
computable that no amount of prompt engineering can imitate:

  learning_path()      given a target, the ordered list of things to learn
                       first, skipping what the student already knows
  diagnose_gaps()      when several separate confusions share one upstream
                       prerequisite, that prerequisite is the real problem
  retrieval_hints()    which concepts to pull extra material for, and which
                       to stop re-explaining

The third closes a loop that was previously open:
retrieval and the graph finally influence each other instead of running in
parallel and being pasted together in a prompt.

The graph algorithms here are deliberately pure functions over plain dicts, so
they are unit testable without a database.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

import asyncpg

logger = logging.getLogger(__name__)

# A student is treated as knowing a concept only above this edge weight.
# Below it the evidence is a single passing mention, which is not mastery.
MASTERY_MIN_WEIGHT = 0.6

# How many separate struggles must share a prerequisite before it is called a
# root cause. Two is enough to be interesting and rare enough to be meaningful.
GAP_MIN_SHARED = 2


def normalise(name: str) -> str:
    """
    The join key between curriculum concepts and per-tenant entity nodes.

    Must match normalise_concept() in migration 012 exactly, or the two layers
    silently fail to line up and every path comes back empty.
    """
    return re.sub(r"[^a-z0-9]+", " ", (name or "").strip().lower()).strip()


@dataclass
class LearnerState:
    """What the student already knows, is stuck on, and wants."""
    mastered:   set[str] = field(default_factory=set)
    struggling: set[str] = field(default_factory=set)
    curious:    set[str] = field(default_factory=set)

    @classmethod
    def from_edges(cls, edges: list[dict]) -> "LearnerState":
        state = cls()
        for e in edges:
            obj = normalise(e.get("object", ""))
            if not obj:
                continue
            pred = e.get("predicate", "")
            if pred == "mastered":
                state.mastered.add(obj)
            elif pred in ("struggles_with", "confused_about"):
                state.struggling.add(obj)
            elif pred in ("curious_about", "wants_to_learn"):
                state.curious.add(obj)
        # A concept cannot be both known and blocking. The temporal graph
        # should already have retired one, but reads here must not depend on
        # extraction having behaved.
        state.mastered -= state.struggling
        return state


# ─────────────────────────────────────────────────────────────────────────────
# PURE GRAPH LOGIC
# ─────────────────────────────────────────────────────────────────────────────
def topological_order(
    targets: set[str],
    prerequisites: dict[str, set[str]],
) -> list[str]:
    """
    Order concepts so every prerequisite precedes what depends on it.

    Kahn's algorithm restricted to the subgraph reachable from `targets`.
    Cycles cannot be ordered, so any concept left over when the queue drains is
    appended in a stable order rather than dropped: a cycle in the extracted
    DAG is a data quality problem, not a reason to hide concepts from a
    learner.
    """
    relevant: set[str] = set()
    queue = deque(targets)
    while queue:
        node = queue.popleft()
        if node in relevant:
            continue
        relevant.add(node)
        queue.extend(prerequisites.get(node, set()))

    indegree = {n: 0 for n in relevant}
    dependents: dict[str, set[str]] = defaultdict(set)
    for node in relevant:
        for prereq in prerequisites.get(node, set()):
            if prereq in relevant:
                indegree[node] += 1
                dependents[prereq].add(node)

    ready = deque(sorted(n for n, d in indegree.items() if d == 0))
    ordered: list[str] = []
    while ready:
        node = ready.popleft()
        ordered.append(node)
        for dep in sorted(dependents[node]):
            indegree[dep] -= 1
            if indegree[dep] == 0:
                ready.append(dep)

    leftover = sorted(relevant - set(ordered))
    if leftover:
        logger.warning("Curriculum cycle detected involving: %s", leftover[:5])
        ordered.extend(leftover)

    return ordered


def learning_path(
    target: str,
    state: LearnerState,
    prerequisites: dict[str, set[str]],
) -> list[str]:
    """
    What to study, in order, to reach `target`.

    Mastered concepts are pruned along with everything only they required, so
    an advanced student gets a short path and a beginner gets a long one from
    the same target.
    """
    target_key = normalise(target)
    ordered = topological_order({target_key}, prerequisites)
    return [c for c in ordered if c not in state.mastered]


def diagnose_gaps(
    state: LearnerState,
    prerequisites: dict[str, set[str]],
) -> list[tuple[str, list[str]]]:
    """
    Find prerequisites shared by several current struggles.

    This is the move a human tutor makes and a chatbot does not: a student
    stuck on backpropagation, gradient descent and Adam does not have three
    problems. They have one, and it is derivatives.

    Returns (shared_prerequisite, [struggles it explains]) ordered by how much
    it explains, excluding anything the student has already mastered.
    """
    explains: dict[str, set[str]] = defaultdict(set)

    for struggle in state.struggling:
        # Everything upstream of this struggle, transitively.
        upstream = topological_order({struggle}, prerequisites)
        for prereq in upstream:
            if prereq == struggle or prereq in state.mastered:
                continue
            # A prerequisite the student is also explicitly stuck on is a
            # symptom, not the root cause, so it is not reported as one.
            if prereq in state.struggling:
                continue
            explains[prereq].add(struggle)

    ranked = [
        (prereq, sorted(caused))
        for prereq, caused in explains.items()
        if len(caused) >= GAP_MIN_SHARED
    ]
    ranked.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    return ranked


def retrieval_hints(
    query_concepts: set[str],
    state: LearnerState,
    prerequisites: dict[str, set[str]],
) -> dict[str, list[str]]:
    """
    Turn learner state into instructions for the retriever.

    expand    concepts to pull extra material for, because the question
              depends on them and the student is not solid on them
    suppress  concepts to stop re-explaining, because they are mastered

    This is where retrieval stops being a pure function of the query. The
    student asks about backpropagation; if the graph shows they are shaky on
    the chain rule, the retriever fetches chain rule material even though the
    question never mentioned it.
    """
    expand: set[str] = set()
    for concept in query_concepts:
        for prereq in prerequisites.get(normalise(concept), set()):
            if prereq not in state.mastered:
                expand.add(prereq)

    # Struggles directly upstream of the question are always worth expanding.
    expand |= {s for s in state.struggling if s in expand or s in query_concepts}

    suppress = {m for m in state.mastered if m not in query_concepts}

    return {
        "expand": sorted(expand)[:5],
        "suppress": sorted(suppress)[:20],
    }


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE ACCESS
# ─────────────────────────────────────────────────────────────────────────────
async def load_prerequisites(
    db: asyncpg.Pool,
    min_confidence: float = 0.5,
) -> dict[str, set[str]]:
    """
    The whole DAG as an adjacency map: concept -> its direct prerequisites.

    Small enough to load wholesale (hundreds of concepts, not millions) and
    much cheaper than a recursive query per turn.
    """
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT concept, prerequisite
            FROM   curriculum_edges
            WHERE  confidence >= $1
            """,
            min_confidence,
        )

    prerequisites: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        prerequisites[r["concept"]].add(r["prerequisite"])
    return dict(prerequisites)


async def concept_details(db: asyncpg.Pool, names: list[str]) -> dict[str, dict]:
    if not names:
        return {}
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT name, display_name, difficulty, summary, source_files
            FROM   curriculum_concepts
            WHERE  name = ANY($1::text[])
            """,
            names,
        )
    return {
        r["name"]: {
            "name": r["name"],
            "display_name": r["display_name"],
            "difficulty": r["difficulty"],
            "summary": r["summary"],
            "source_files": list(r["source_files"] or []),
        }
        for r in rows
    }


async def curriculum_is_loaded(db: asyncpg.Pool) -> bool:
    """
    Whether a curriculum has been built.

    Every consumer degrades gracefully when it has not: the product works
    exactly as it did before, just without prerequisite reasoning.
    """
    try:
        async with db.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM curriculum_edges")
        return bool(count)
    except asyncpg.UndefinedTableError:
        return False   # migration 012 has not been applied
    except Exception as exc:  # noqa: BLE001
        logger.warning("Curriculum availability check failed: %s", exc)
        return False
