"""Tenant-scoped destructive operations kept small enough to regression test."""

from __future__ import annotations

import uuid
from typing import Protocol


class ExecutableConnection(Protocol):
    async def execute(self, query: str, *args: object) -> object: ...


# Dependency order is intentional. Turns are deleted first because they are the
# source-of-truth lock used by background extraction: once this transaction
# owns those rows, no stale task can recreate memory after reset. Graph edges
# still precede nodes for FK integrity, and session rows disappear last.
TENANT_CLEAR_STATEMENTS = (
    "DELETE FROM conversation_turns WHERE tenant_id = $1",
    "DELETE FROM relation_edges     WHERE tenant_id = $1",
    "DELETE FROM entity_aliases     WHERE tenant_id = $1",
    "DELETE FROM entity_nodes       WHERE tenant_id = $1",
    "DELETE FROM chat_sessions      WHERE tenant_id = $1",
)


async def clear_tenant_data(
    connection: ExecutableConnection,
    tenant_id: uuid.UUID,
) -> None:
    """Delete all user-owned memory while preserving the tenant identity."""
    for statement in TENANT_CLEAR_STATEMENTS:
        await connection.execute(statement, tenant_id)
