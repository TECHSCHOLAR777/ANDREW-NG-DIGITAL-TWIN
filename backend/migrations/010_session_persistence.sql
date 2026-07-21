-- ============================================================
-- Migration 010: Session Persistence
--
-- Problem: conversations existed only in React state. A refresh
-- destroyed every session, and the sidebar was a list of things
-- that would not survive the next reload.
--
-- The strange part is that the backend was ALREADY writing every
-- turn to conversation_turns and no code ever read them back. The
-- durable store existed and went unused, while the client held the
-- only copy of the conversation.
--
-- This migration adds the missing piece: a session record with a
-- stable title, so the sidebar can be rebuilt from the server. Turns
-- themselves were always there.
-- ============================================================

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT 'New conversation',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sidebar query: this tenant's sessions, most recently active first
CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant_updated
    ON chat_sessions (tenant_id, updated_at DESC);

CREATE TRIGGER trg_chat_sessions_updated_at
BEFORE UPDATE ON chat_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ── Backfill from existing turns ────────────────────────────
-- Anyone upgrading has conversation history with no session rows.
-- The title comes from the first user message, which is what the
-- frontend was doing client-side anyway.
INSERT INTO chat_sessions (id, tenant_id, title, created_at, updated_at)
SELECT
    ct.session_id,
    ct.tenant_id,
    COALESCE(
        (
            SELECT left(regexp_replace(inner_ct.content, '\s+', ' ', 'g'), 60)
            FROM   conversation_turns inner_ct
            WHERE  inner_ct.session_id = ct.session_id
              AND  inner_ct.tenant_id  = ct.tenant_id
              AND  inner_ct.role       = 'user'
            ORDER  BY inner_ct.turn_index ASC
            LIMIT  1
        ),
        'New conversation'
    ),
    MIN(ct.created_at),
    MAX(ct.created_at)
FROM   conversation_turns ct
GROUP  BY ct.session_id, ct.tenant_id
ON CONFLICT (id) DO NOTHING;


-- ============================================================
-- Turn index integrity
--
-- turn_index was computed with a COUNT(*) and then inserted, so two
-- concurrent turns in one session could receive the same index. The
-- unique index makes that collision an error instead of silent
-- history corruption, and the application computes the next index
-- inside the INSERT so the read and the write are one statement.
-- ============================================================
-- Deduplicate any existing collisions before adding the constraint,
-- keeping the earliest row for each position.
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY tenant_id, session_id, turn_index
               ORDER BY created_at ASC, id ASC
           ) AS rn
    FROM conversation_turns
)
UPDATE conversation_turns ct
SET    turn_index = ct.turn_index + 10000 + ranked.rn
FROM   ranked
WHERE  ct.id = ranked.id
  AND  ranked.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_turns_position
    ON conversation_turns (tenant_id, session_id, turn_index);
