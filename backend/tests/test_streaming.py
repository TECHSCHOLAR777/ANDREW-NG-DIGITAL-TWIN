import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.streaming import (  # noqa: E402
    SentenceAccumulator,
    split_complete_sentences,
)


def test_sentence_is_emitted_before_stream_finishes():
    accumulator = SentenceAccumulator()

    assert accumulator.push("The key idea is to follow the slope") == []
    assert accumulator.push(" downhill. Then update the weights") == [
        "The key idea is to follow the slope downhill."
    ]
    assert accumulator.flush() == ["Then update the weights"]
    assert accumulator.full_text == (
        "The key idea is to follow the slope downhill. Then update the weights"
    )


def test_abbreviations_and_decimals_do_not_split_voice_chunks():
    sentences, remainder = split_complete_sentences(
        "Dr. Ng might choose 0.01 as the learning rate. That is a starting point."
    )

    assert sentences == [
        "Dr. Ng might choose 0.01 as the learning rate.",
        "That is a starting point.",
    ]
    assert remainder == ""


def test_short_sentence_is_merged_to_avoid_a_tiny_tts_request():
    sentences, remainder = split_complete_sentences(
        "That is the first useful intuition. Right. Now test it with an example."
    )

    assert sentences == [
        "That is the first useful intuition. Right.",
        "Now test it with an example.",
    ]
    assert remainder == ""
