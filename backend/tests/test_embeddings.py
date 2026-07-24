"""
Regression tests for the async embedding helpers used on request paths.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import embeddings  # noqa: E402


def test_embed_document_batch_uses_one_provider_call():
    calls: list[tuple[list[str], str, str]] = []
    original = embeddings.encode_sync

    def fake_encode(
        texts: list[str],
        api_key: str = "",
        task_type: str = embeddings.DOCUMENT,
    ) -> list[list[float]]:
        calls.append((list(texts), api_key, task_type))
        return [[float(index)] for index, _ in enumerate(texts)]

    embeddings.encode_sync = fake_encode
    try:
        result = asyncio.run(
            embeddings.embed_document_batch(["Maya", "Retail"], "test-key")
        )
    finally:
        embeddings.encode_sync = original

    assert result == [[0.0], [1.0]]
    assert calls == [(["Maya", "Retail"], "test-key", embeddings.DOCUMENT)]


def test_embed_document_batch_skips_provider_for_empty_input():
    assert asyncio.run(embeddings.embed_document_batch([])) == []
