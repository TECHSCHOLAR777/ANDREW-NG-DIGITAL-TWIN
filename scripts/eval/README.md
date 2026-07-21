# Evaluation

Three layers, because this system has three quality surfaces that fail
independently. A change can improve retrieval while degrading persona, or fix
persona while corrupting memory, and a single overall score would hide both.

| Layer | Measures | Needs | Script |
|---|---|---|---|
| Corpus style | What Andrew's real writing looks like | nothing | `corpus_style.py` |
| Persona | Rule violations, and distance from that style | API key (or a transcript) | `persona_eval.py` |
| Retrieval | recall@k, MRR, abstention calibration | API key to build, database to run | `golden_set.py`, `retrieval_eval.py` |
| Memory | Whether the graph believes the right things | API key and database | `memory_eval.py` |

Unit tests in `backend/tests/` cover the pure logic (chunking, sanitisation,
routing, validators) and need neither. Those are what CI runs.

## Quick start

```bash
# 1. Style baseline. Runs offline, takes about a minute.
python scripts/eval/corpus_style.py --save data/baselines/corpus_style.json

# 2. Persona check against pre-collected answers, no API key needed.
python scripts/eval/persona_eval.py --offline samples.jsonl

# 3. Retrieval golden set. One model call per question, roughly a cent for 100.
python scripts/eval/golden_set.py --n 100 --negatives 20

# 4. Retrieval measurement, with ablations.
python scripts/eval/retrieval_eval.py --ablate

# 5. Memory scenarios.
python scripts/eval/memory_eval.py
```

## What each layer is actually for

### Corpus style

Persona fidelity used to be an opinion. Someone reads an answer, decides it
sounds right, and that was the evaluation.

This computes the reference from the source material: sentence length,
connective habits, hedging rate, pronoun balance, split by spoken versus
written. Most persona projects cannot do this because they have no corpus of
the person. This one does.

It also audits the persona's own rules. The first run produced a finding worth
keeping: phrases the prompt bans absolutely do appear in the real corpus, at
roughly 0.002 to 0.016 occurrences per 1000 words. So "he never says this" is
false. The bans are still correct, but for a different reason, which is that a
language model reaches for them a thousand times more often than he does. That
distinction is now recorded in `services/persona.py` next to the rule.

### Persona

Two scores. The mechanical one counts violations of rules that have an
objective answer: banned openers, comprehension-check phrases, rendered lists,
headings, unfinished sentences. The stylistic one reports signed distance from
the corpus baseline, per metric, because a single number hides direction.

Exits non-zero below a 90% clean rate, so it can gate a release.

### Retrieval

Golden questions are labelled by `(source_file, chunk_index)` rather than
database UUID, so the set survives a re-ingest. Questions are generated with an
explicit instruction to paraphrase, because a question that quotes its source
passage is solved by lexical overlap and measures nothing.

Two things here are not standard:

**Negatives.** The set includes questions the corpus cannot answer. Without
them you cannot tell whether the system knows when it has nothing, which for a
tutor is the difference between trustworthy and merely fluent.
`RETRIEVAL_MIN_COSINE` was set to 0.35 by intuition; this computes the
threshold that best separates the two populations, and reports the errors it
would make in both directions.

**Ablations.** `--ablate` re-runs with neighbour expansion off, then with query
rewriting off. Both were added on reasoning alone. This turns that reasoning
into a number, and is equally willing to show that they did not help.

### Memory

The layer that matters most and is least often built, because it tests the
actual claim: that the twin remembers a student, notices when they have
understood something, and stops treating a resolved difficulty as current.

Each scenario drives real turns through the real pipeline against a scratch
tenant, runs extraction inline rather than as a background task so assertions
see a settled graph, then checks what the graph believes and deletes the
tenant.

Current scenarios:

- `learning_progress` a struggle is retired once the student demonstrates understanding
- `alias_consolidation` "NNs" and "neural networks" resolve to one node
- `small_talk` greetings create no beliefs at all
- `injection_defence` instruction-shaped text never becomes trusted evidence
- `cross_session` a belief formed in one session is visible from another

`--keep` preserves the scratch tenant so you can inspect the graph by hand
after a failure.

## Adding a scenario

Scenarios are declarative. Add turns and checks to `SCENARIOS` in
`memory_eval.py`; the helpers (`live_edge`, `invalidated_edge`, `no_live_edge`,
`single_node_for`, `max_edges`, `no_evidence_containing`) cover most cases.

## Cost

Building a 100-question golden set is about a cent. A full retrieval run with
ablations is three passes of embedding and search, mostly local. The memory
scenarios are roughly a dozen generations. None of this is expensive enough to
be a reason not to run it.

## Honest status

The offline layers (unit tests, corpus style, persona offline scoring) have
been run and pass. The retrieval and memory harnesses are written and their
pure logic is verified, but they have not been executed end to end, because the
configured `DATABASE_URL` is not currently valid. First run against a live
database should be treated as a shakedown.
