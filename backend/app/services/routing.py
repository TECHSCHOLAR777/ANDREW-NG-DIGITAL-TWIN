"""
services/routing.py
─────────────────────────────────────────────────────────────────────────────
Decide what kind of turn this is, so the pipeline can spend effort accordingly.

Every message used to cost the same: embed, two database searches, graph
summary, full generation with a large thinking budget, then extraction. "hi"
and "derive the backprop update for a two layer network" were treated
identically.

That is wasteful in the obvious direction and wrong in a subtler one. A
greeting retrieves ten chunks of noise which then sit in the prompt as though
they were relevant, and small talk gets mined for knowledge-graph triples,
polluting memory with nothing.

The persona itself already says the four-beat teaching structure applies only
to new technical concepts, "not to greetings, small talk, opinions on AI's
future, career or strategy advice, simple factual lookups, or quick follow-ups".
So the model was already being asked to classify the turn and behave
accordingly, in the same call, with no explicit representation of the decision.
This makes the decision explicit and cheap.

Deliberately heuristic rather than an LLM call: classification must not add
latency to the very turns it exists to make fast.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Turn kinds. Kept small on purpose; each one must earn a different pipeline.
GREETING = "greeting"
FOLLOWUP = "followup"
CONCEPT  = "concept"
OPINION  = "opinion"

_GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|yo|good\s+(morning|afternoon|evening)|thanks?|thank\s+you|"
    r"ok|okay|cool|nice|got\s+it|bye|goodbye|see\s+you|sup)\b[\s!.,?]*$",
    re.IGNORECASE,
)

_OPINION_RE = re.compile(
    r"\b(what do you think|your (opinion|view|take)|should i|career|"
    r"is it worth|future of|will ai|do you believe|advice)\b",
    re.IGNORECASE,
)

_CONCEPT_RE = re.compile(
    r"\b(what is|what are|how does|how do|explain|derive|prove|why does|"
    r"difference between|intuition|formula|equation|algorithm|implement)\b",
    re.IGNORECASE,
)


@dataclass
class TurnPlan:
    kind: str
    retrieve: bool          # run corpus retrieval at all
    top_k: int              # how many chunks when retrieving
    extract_triples: bool   # feed this turn to the knowledge graph
    reason: str


def classify_turn(message: str, has_history: bool) -> TurnPlan:
    """
    Classify one incoming message.

    Ordering matters: greeting is checked first because "thanks!" should never
    be treated as a concept question just because it is short.
    """
    text = (message or "").strip()
    words = re.findall(r"[A-Za-z']+", text)

    if not text or _GREETING_RE.match(text):
        return TurnPlan(
            kind=GREETING, retrieve=False, top_k=0, extract_triples=False,
            reason="greeting or acknowledgement: nothing to retrieve or remember",
        )

    if _OPINION_RE.search(text):
        return TurnPlan(
            kind=OPINION, retrieve=True, top_k=6, extract_triples=True,
            reason="opinion, career or strategy question: lighter retrieval, no teaching engine",
        )

    if _CONCEPT_RE.search(text) or len(words) > 12:
        return TurnPlan(
            kind=CONCEPT, retrieve=True, top_k=10, extract_triples=True,
            reason="technical concept question: full retrieval and teaching structure",
        )

    if has_history and len(words) <= 12:
        return TurnPlan(
            kind=FOLLOWUP, retrieve=True, top_k=8, extract_triples=True,
            reason="short message with prior context: follow-up, query will be rewritten",
        )

    return TurnPlan(
        kind=CONCEPT, retrieve=True, top_k=10, extract_triples=True,
        reason="default: treat as a substantive question",
    )
