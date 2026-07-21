"""
services/streaming.py
─────────────────────────────────────────────────────────────────────────────
Turn a token stream into sentences, so speech can start before the answer ends.

WHY THIS SHAPE
──────────────
The old turn ran three complete stages in series:

    recognise speech (~0.5s)
      -> generate the ENTIRE answer (5 to 20s)
        -> synthesise sentence 1, then 2, then 3 ... (2 to 8s each)

Floor: roughly 8 to 30 seconds before the user hears anything. Every stage was
individually acceptable when tested alone, which is exactly why nobody caught
it; the sum is what a person experiences.

Overlapping them changes the number, not the models:

    recognise -> stream tokens -> cut at sentence 1 (~0.7s) -> synthesise it
                              while sentence 2 is still being generated

Same hardware, roughly 2 seconds to first audio.

The sentence splitter has to be a little careful. Cutting on every period would
break "Dr. Ng" and "0.001" into fragments, and each fragment becomes a separate
TTS request with its own prosody, which sounds wrong even when the text is
right.
"""

from __future__ import annotations

import re

# Abbreviations that end in a period without ending a sentence.
_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "st",
    "e.g", "i.e", "etc", "vs", "fig", "eq", "approx", "no",
    "al", "ph.d", "b.sc", "m.sc", "inc", "ltd", "co",
}

_SENTENCE_END = re.compile(r"[.!?]")
MIN_SENTENCE_CHARS = 24


def _ends_sentence(buffer: str, index: int) -> bool:
    """
    Decide whether the punctuation at `index` really ends a sentence.

    Rejects three common false positives: known abbreviations, decimals inside
    numbers, and single-letter initials.
    """
    char = buffer[index]
    if char not in ".!?":
        return False

    # "!" and "?" are unambiguous enough in prose.
    if char != ".":
        return True

    before = buffer[:index]
    after = buffer[index + 1:]

    # Decimal number: digit '.' digit
    if before and before[-1].isdigit() and after and after[0].isdigit():
        return False

    # Abbreviation: last token before the period
    tail = re.split(r"[\s(]", before)[-1].lower().rstrip(".")
    if tail in _ABBREVIATIONS:
        return False

    # Single letter initial, as in "A. Ng"
    if len(tail) == 1 and tail.isalpha():
        return False

    # A real boundary is followed by whitespace or end of buffer
    if after and not after[0].isspace():
        return False

    return True


def split_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """
    Split off every complete sentence, returning (sentences, remainder).

    Very short sentences are held back and merged forward. "Right." on its own
    is a whole TTS round trip for one word, and it sounds clipped when spoken
    in isolation.
    """
    sentences: list[str] = []
    start = 0
    i = 0

    while i < len(buffer):
        if _SENTENCE_END.match(buffer[i]) and _ends_sentence(buffer, i):
            end = i + 1
            # Absorb trailing quotes or brackets that belong to this sentence
            while end < len(buffer) and buffer[end] in '"\')]':
                end += 1
            candidate = buffer[start:end].strip()
            if candidate:
                if sentences and len(candidate) < MIN_SENTENCE_CHARS:
                    sentences[-1] = f"{sentences[-1]} {candidate}"
                else:
                    sentences.append(candidate)
            start = end
            i = end
            continue
        i += 1

    return sentences, buffer[start:]


class SentenceAccumulator:
    """
    Feed it token fragments, get back complete sentences as they finish.

    Usage:
        acc = SentenceAccumulator()
        for fragment in token_stream:
            for sentence in acc.push(fragment):
                emit(sentence)
        for sentence in acc.flush():
            emit(sentence)
    """

    def __init__(self) -> None:
        self._buffer = ""
        self.full_text = ""

    def push(self, fragment: str) -> list[str]:
        if not fragment:
            return []
        self._buffer += fragment
        self.full_text += fragment
        sentences, self._buffer = split_complete_sentences(self._buffer)
        return sentences

    def flush(self) -> list[str]:
        """Emit whatever is left when the stream ends."""
        remaining = self._buffer.strip()
        self._buffer = ""
        return [remaining] if remaining else []
