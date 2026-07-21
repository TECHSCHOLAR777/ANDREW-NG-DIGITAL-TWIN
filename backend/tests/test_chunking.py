"""
Tests for scripts/chunking.py.

Chunking sits upstream of everything: a defect here degrades every embedding
in the corpus and there is no downstream fix for it. The two regression tests
at the bottom encode bugs that a synthetic test missed and only appeared when
the chunker was run over the real 529-file corpus.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from chunking import (  # noqa: E402
    MAX_CHARS,
    MIN_FRAGMENT_CHARS,
    NOISE_CHARS,
    Chunk,
    chunk_document,
)


def test_headings_become_a_trail():
    body = "We minimise the cost function by stepping downhill, checking the slope. " * 4
    rate = "If the learning rate is too large the algorithm diverges outright. " * 4
    doc = f"""# CS229 Lecture Notes

## Gradient Descent

{body}

### Learning rate

{rate}
"""
    chunks = chunk_document(doc, doc_title="CS229 Notes")
    trails = [" > ".join(c.heading_trail) for c in chunks]
    assert any("Gradient Descent" in t for t in trails)
    assert any("Learning rate" in t for t in trails)


def test_subsections_nest_under_their_parent():
    doc = """# Doc

## Parent Section

Body text for the parent section that is long enough to survive the minimum
fragment filter without being merged away into nothing at all.

### Child Section

Body text for the child section, also long enough to stand on its own as a
chunk rather than being dropped as a fragment.
"""
    chunks = chunk_document(doc, doc_title="Doc")
    child = [c for c in chunks if "Child Section" in c.heading_trail]
    assert child, "child section produced no chunk"
    assert "Parent Section" in child[0].heading_trail


def test_embed_text_carries_context_but_body_stays_clean():
    """The reader sees the passage; the embedding sees the passage plus where
    it came from. Mixing those up would put heading noise in the UI."""
    c = Chunk(text="The update rule adjusts theta.", index=0,
              heading_trail=["CS229", "Gradient Descent"])
    assert c.embed_text.startswith("[CS229 > Gradient Descent]")
    assert "The update rule adjusts theta." in c.embed_text
    assert c.text == "The update rule adjusts theta."


def test_no_heading_trail_means_embed_text_equals_body():
    c = Chunk(text="Plain text.", index=0, heading_trail=[])
    assert c.embed_text == "Plain text."


def test_long_sections_split_with_sentence_overlap():
    """A boundary that lands mid-argument must not sever it, so consecutive
    pieces share a sentence or two."""
    body = " ".join(f"Sentence number {i} explains one more detail." for i in range(120))
    doc = f"# Doc\n\n## Long Section\n\n{body}\n"
    chunks = chunk_document(doc, doc_title="Doc")
    assert len(chunks) > 1

    first_tail = " ".join(chunks[0].text.split()[-6:])
    assert first_tail in chunks[1].text, "no overlap carried into the next chunk"


def test_chunks_respect_the_size_ceiling():
    body = " ".join(f"Sentence {i} carries some content." for i in range(400))
    chunks = chunk_document(f"# Doc\n\n{body}\n", doc_title="Doc")
    assert all(len(c.text) <= MAX_CHARS for c in chunks)


def test_indexes_are_sequential_from_zero():
    doc = "# Doc\n\n" + "\n\n".join(
        f"## Section {i}\n\n" + ("Body sentence for this section. " * 12)
        for i in range(5)
    )
    chunks = chunk_document(doc, doc_title="Doc")
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_document_without_headings_still_chunks():
    text = "Just prose. " * 300
    chunks = chunk_document(text, doc_title="Plain Doc")
    assert chunks
    assert all(c.text.strip() for c in chunks)


def test_empty_document_produces_nothing():
    assert chunk_document("", doc_title="Empty") == []
    assert chunk_document("   \n\n  ", doc_title="Empty") == []


def test_duplicate_title_and_heading_are_collapsed():
    """A file called cs229_notes_1.txt whose first heading is 'CS229 Notes 1'
    must not produce 'CS229 Notes 1 > CS229 Notes 1' on every chunk."""
    doc = "# CS229 Notes 1\n\n" + ("Body content here. " * 20)
    chunks = chunk_document(doc, doc_title="CS229 Notes 1")
    for c in chunks:
        assert len(c.heading_trail) == len(set(c.heading_trail))
        assert " > ".join(c.heading_trail).count("CS229 Notes 1") == 1


# ── Regressions found by running over the real corpus ────────────────────────

def test_collector_metadata_is_not_treated_as_a_heading():
    """REGRESSION: '# Date:', '# Author:' and 'Extracted: <timestamp>' were
    being parsed as section headings, so chunks were labelled with a timestamp
    instead of their topic and that noise was prefixed onto every embedding."""
    doc = """# Title: Some Blog Post
# Date:
# Author:
Extracted: 2026-06-01T19:15:11.454966

# Real Heading

Actual body content that should be chunked normally and carry the real
heading rather than a metadata line, with enough text to survive filtering.
"""
    chunks = chunk_document(doc, doc_title="Some Blog Post")
    joined = " ".join(" > ".join(c.heading_trail) for c in chunks).lower()
    for leaked in ("extracted:", "date:", "author:", "2026-06-01"):
        assert leaked not in joined, f"metadata {leaked!r} leaked into a heading trail"


def test_noise_is_dropped_but_real_short_content_is_kept():
    """REGRESSION, twice over.

    First: 17-character chunks survived, and a fragment that short can win a
    keyword match while contributing nothing.

    Then the fix over-corrected by DROPPING everything undersized. Measured
    across the corpus that lost only 0.07% of the text, but the losses included
    short pull-quotes from Karpathy and Hinton. Rare is not the same as
    unimportant, so small fragments are now absorbed into a neighbour and only
    genuine noise is discarded."""
    quote = '> "Read enough to develop your intuitions, then trust your intuitions."'
    doc = f"""# Doc

## Noise

x

## Quote

{quote}

## Body

{"Real content that easily clears the minimum on its own. " * 6}
"""
    chunks = chunk_document(doc, doc_title="Doc")
    joined = " ".join(c.text for c in chunks)

    assert "trust your intuitions" in joined, "a real short quote was discarded"
    assert all(len(c.text.strip()) >= NOISE_CHARS for c in chunks)
    assert "\nx\n" not in joined, "the stray noise line survived"


def test_short_section_survives_by_merging_not_vanishing():
    short = "A brief but meaningful remark worth keeping in the corpus."
    doc = f"""# Doc

## Main

{"Substantial body content for the main section. " * 8}

## Aside

{short}
"""
    chunks = chunk_document(doc, doc_title="Doc")
    joined = " ".join(c.text for c in chunks)
    assert short in joined
    # The heading survives as text even though the trail was absorbed.
    assert "Aside" in joined


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
