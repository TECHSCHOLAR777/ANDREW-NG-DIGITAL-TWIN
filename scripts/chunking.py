"""
scripts/chunking.py
─────────────────────────────────────────────────────────────────────────────
Structure-aware chunking for the corpus.

WHAT WAS WRONG
──────────────
The previous chunker packed paragraphs up to 1000 characters with:

  * no overlap between chunks
  * no document or section title attached
  * no awareness of headings, so a chunk could begin mid-explanation

CS229 notes and Machine Learning Yearning are sequentially dependent: chunk 47
uses notation that chunk 46 introduced. Retrieval returns 47 alone, the model
never sees where theta came from, and it fills the gap from parametric memory.
The answer reads fine, which is exactly what makes the failure dangerous.

Migration 008 added neighbour expansion at QUERY time, which recovers the
surrounding text. This fixes the other half, at INGEST time:

  1. Split on real section boundaries, so a chunk starts where an idea starts.
  2. Carry a heading trail ("CS229 Notes 1 > Gradient Descent") into the text
     that gets embedded, so a fragment about "the update rule" is no longer
     identical in vector space to every other update rule in the corpus.
  3. Overlap consecutive chunks by a sentence or two, so a boundary that lands
     mid-argument does not sever it.

The heading trail is stored separately from the body, so the retrieved text
shown to a user stays clean while the embedded text carries the context.

The technical report currently claims chunking is done "by section headers and
book chapters instead of arbitrary character limits". That was aspirational
before this file existed; it is true now.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TARGET_CHARS = 1100
MIN_CHARS = 260
MAX_CHARS = 1900
OVERLAP_SENTENCES = 2
MIN_FRAGMENT_CHARS = 120
NOISE_CHARS = 25          # below this a fragment is a stray char or page number

# Headings seen across the corpus: markdown, numbered sections, and the
# ALL-CAPS lines the transcript cleaner produces.
_HEADING_PATTERNS = [
    re.compile(r"^\s{0,3}(#{1,6})\s+(?P<text>\S.*?)\s*$"),
    re.compile(r"^\s*(?P<num>\d+(?:\.\d+)*)[.)]?\s+(?P<text>[A-Z][^.!?]{3,80})\s*$"),
    re.compile(r"^\s*(?P<text>(?:CHAPTER|SECTION|PART|LECTURE|APPENDIX)\b[^\n]{0,80})\s*$", re.I),
    re.compile(r"^\s*(?P<text>[A-Z][A-Z0-9 ,'\-()]{6,70})\s*$"),
]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


@dataclass
class Chunk:
    text: str                 # clean body, shown to the reader
    index: int
    heading_trail: list[str] = field(default_factory=list)

    @property
    def embed_text(self) -> str:
        """
        What actually gets embedded.

        Prefixing the heading trail is the cheap half of contextual retrieval:
        it disambiguates fragments that are lexically similar but belong to
        different topics, at zero inference cost.
        """
        if not self.heading_trail:
            return self.text
        return f"[{' > '.join(self.heading_trail)}]\n{self.text}"


# Header lines the collectors emit ("# Date:", "# Author:", "Extracted: ...").
# Without this they were parsed as section headings and ended up as the
# heading trail prefixed onto embeddings, so chunks were being labelled with a
# timestamp instead of their topic.
_METADATA_LINE = re.compile(
    r"^\s*#?\s*(title|url|date|domain|author|source|extracted|scraped|"
    r"published|updated|link|category|tags?)\s*:",
    re.IGNORECASE,
)


def _match_heading(line: str) -> tuple[int, str] | None:
    """Return (level, text) when a line looks like a heading."""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return None
    if _METADATA_LINE.match(stripped):
        return None
    # A line ending in sentence punctuation is prose, not a heading.
    if stripped.endswith((".", ",", ";", ":")) and not stripped.isupper():
        return None

    for i, pattern in enumerate(_HEADING_PATTERNS):
        m = pattern.match(line)
        if not m:
            continue
        if i == 0:
            return len(m.group(1)), m.group("text").strip()
        if i == 1:
            return m.group("num").count(".") + 1, m.group("text").strip()
        return 1 if i == 2 else 2, m.group("text").strip()
    return None


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _tail_sentences(text: str, count: int) -> str:
    sentences = _split_sentences(text)
    return " ".join(sentences[-count:]) if sentences else ""


def _split_oversized(body: str) -> list[str]:
    """Break a section that exceeds MAX_CHARS on sentence boundaries."""
    sentences = _split_sentences(body)
    parts: list[str] = []
    current = ""

    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > TARGET_CHARS:
            parts.append(current.strip())
            # Overlap: carry the tail forward so an argument split across the
            # boundary survives in both pieces.
            current = _tail_sentences(current, OVERLAP_SENTENCES) + " " + sentence
        else:
            current = f"{current} {sentence}".strip()

    if current.strip():
        parts.append(current.strip())
    return parts


def chunk_document(text: str, doc_title: str | None = None) -> list[Chunk]:
    """
    Split a cleaned document into retrieval chunks.

    Sections are found first, then oversized sections are split on sentence
    boundaries with overlap, then undersized neighbours are merged so the
    corpus does not fill with one-line fragments.
    """
    lines = text.splitlines()
    trail: list[str] = [doc_title] if doc_title else []
    sections: list[tuple[list[str], str]] = []
    buffer: list[str] = []
    current_trail = list(trail)

    for line in lines:
        heading = _match_heading(line)
        if heading:
            if buffer and "".join(buffer).strip():
                sections.append((list(current_trail), "\n".join(buffer).strip()))
            buffer = []
            level, heading_text = heading
            base = [doc_title] if doc_title else []
            # Keep only ancestors shallower than this heading, so the trail
            # reflects real nesting rather than every heading seen so far.
            kept = [h for h in current_trail[len(base):]][: max(0, level - 1)]
            current_trail = base + kept + [heading_text]
        else:
            buffer.append(line)

    if buffer and "".join(buffer).strip():
        sections.append((list(current_trail), "\n".join(buffer).strip()))

    if not sections:
        sections = [(list(trail), text.strip())]

    # Expand oversized sections
    expanded: list[tuple[list[str], str]] = []
    for heading_trail, body in sections:
        if not body:
            continue
        if len(body) <= MAX_CHARS:
            expanded.append((heading_trail, body))
        else:
            for part in _split_oversized(body):
                expanded.append((heading_trail, part))

    # Merge runs that are too small to stand alone, but only within the same
    # section, so merging never fuses unrelated topics.
    merged: list[tuple[list[str], str]] = []
    for heading_trail, body in expanded:
        if (
            merged
            and len(merged[-1][1]) < MIN_CHARS
            and merged[-1][0] == heading_trail
            and len(merged[-1][1]) + len(body) <= MAX_CHARS
        ):
            merged[-1] = (heading_trail, f"{merged[-1][1]}\n\n{body}")
        else:
            merged.append((heading_trail, body))

    kept = _absorb_small_fragments(merged)

    return [
        Chunk(text=body, index=i, heading_trail=_dedupe_trail(heading_trail))
        for i, (heading_trail, body) in enumerate(kept)
        if body.strip()
    ]


def _absorb_small_fragments(
    sections: list[tuple[list[str], str]],
) -> list[tuple[list[str], str]]:
    """
    Fold undersized chunks into a neighbour instead of discarding them.

    An earlier version simply dropped anything under the minimum. Measured over
    the corpus that discarded only 0.07% of the text, which sounded harmless
    until the discarded samples were inspected: they included short pull-quotes
    from Karpathy and Hinton, which is precisely the quotable material a tutor
    wants to reach for. Rarity is not the same as unimportance.

    So a small fragment merges into the previous chunk (or the next, when it is
    first). When the fragment came from its own section, its heading is carried
    into the body text so the topic survives even though the trail does not.
    Only genuine noise, a stray character or a page number, is dropped.
    """
    out: list[tuple[list[str], str]] = []

    for heading_trail, body in sections:
        text = body.strip()
        if not text:
            continue

        if len(text) >= MIN_FRAGMENT_CHARS:
            out.append((heading_trail, text))
            continue

        if len(text) < NOISE_CHARS:
            continue   # a stray character or page number, genuinely nothing

        if out:
            prev_trail, prev_body = out[-1]
            heading = heading_trail[-1] if heading_trail else ""
            prefix = (
                f"{heading}\n"
                if heading and (not prev_trail or heading != prev_trail[-1])
                else ""
            )
            out[-1] = (prev_trail, f"{prev_body}\n\n{prefix}{text}")
        else:
            # Nothing before it: hold and prepend to whatever comes next.
            out.append((heading_trail, text))

    # A leading fragment may still be undersized; fold it into its successor.
    if len(out) > 1 and len(out[0][1]) < MIN_FRAGMENT_CHARS:
        first_trail, first_body = out[0]
        next_trail, next_body = out[1]
        out[1] = (next_trail, f"{first_body}\n\n{next_body}")
        out.pop(0)

    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _dedupe_trail(trail: list[str]) -> list[str]:
    """
    Drop empty and near-duplicate entries.

    A file named "cs229_notes_1.txt" whose first heading is "CS229 Lecture
    Notes 1" would otherwise produce "CS229 Notes 1 > CS229 Lecture Notes 1",
    which wastes prefix tokens on every chunk in the document.
    """
    out: list[str] = []
    for item in (h.strip() for h in trail if h and h.strip()):
        key = _norm(item)
        if any(key in _norm(prev) or _norm(prev) in key for prev in out):
            continue
        out.append(item)
    return out
