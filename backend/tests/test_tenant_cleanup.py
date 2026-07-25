"""Regression coverage for the complete history-reset contract."""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tenant_cleanup import (  # noqa: E402
    TENANT_CLEAR_STATEMENTS,
    clear_tenant_data,
)


class RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query: str, *args: object) -> None:
        self.calls.append((query, args))


def test_reset_deletes_transcript_and_sidebar_sessions():
    assert any("conversation_turns" in sql for sql in TENANT_CLEAR_STATEMENTS)
    assert any("chat_sessions" in sql for sql in TENANT_CLEAR_STATEMENTS)
    assert "conversation_turns" in TENANT_CLEAR_STATEMENTS[0]
    assert "chat_sessions" in TENANT_CLEAR_STATEMENTS[-1]


def test_reset_executes_every_delete_for_the_same_tenant_in_order():
    tenant_id = uuid.uuid4()
    connection = RecordingConnection()

    asyncio.run(clear_tenant_data(connection, tenant_id))

    assert [query for query, _ in connection.calls] == list(
        TENANT_CLEAR_STATEMENTS
    )
    assert all(args == (tenant_id,) for _, args in connection.calls)


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
