-- ============================================================
-- Migration 004: Production Hardening
-- Adds the SPO unique constraint needed for ON CONFLICT upsert,
-- plus BRIN index for time-series queries and a materialized
-- view for the student learning summary dashboard.
-- ============================================================

-- ── Unique constraint for (S, P, O) upsert ──────────────────
-- Required by the TripletExtractor's ON CONFLICT DO UPDATE clause.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_relation_edges_spo'
          AND conrelid = 'relation_edges'::regclass
    ) THEN
        ALTER TABLE relation_edges
        ADD CONSTRAINT uq_relation_edges_spo
        UNIQUE (tenant_id, subject_id, predicate, object_id);
    END IF;
END
$$;

-- ── BRIN index for time-range scans ─────────────────────────
-- Very low write overhead; useful for "graph as of date X" queries.
CREATE INDEX IF NOT EXISTS idx_relation_edges_created_brin
ON relation_edges USING BRIN (created_at);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_created_brin
ON conversation_turns USING BRIN (created_at);

-- ── Partial index: only un-processed turns ───────────────────
-- Makes the "find turns needing triplet extraction" query instant.
CREATE INDEX IF NOT EXISTS idx_turns_unprocessed
ON conversation_turns (tenant_id, created_at)
WHERE triplets_extracted = FALSE;

-- ============================================================
-- MATERIALIZED VIEW: Student Learning Summary
-- Refreshed asynchronously; used by the dashboard sidebar.
-- Refresh with: REFRESH MATERIALIZED VIEW CONCURRENTLY student_learning_summary;
-- ============================================================
CREATE MATERIALIZED VIEW IF NOT EXISTS student_learning_summary AS
SELECT
    re.tenant_id,
    re.predicate,
    en_obj.canonical_name   AS concept,
    en_obj.node_type        AS concept_type,
    COUNT(*)                AS observation_count,
    MAX(re.weight)          AS max_weight,
    AVG(re.weight)          AS avg_weight,
    MAX(re.updated_at)      AS last_seen
FROM
    relation_edges re
    JOIN entity_nodes en_subj ON en_subj.id = re.subject_id
    JOIN entity_nodes en_obj  ON en_obj.id  = re.object_id
WHERE
    en_subj.node_type = 'Student'       -- edges FROM a student node
    AND re.predicate IN (
        'struggles_with', 'mastered', 'curious_about',
        'confused_about', 'wants_to_learn'
    )
GROUP BY
    re.tenant_id,
    re.predicate,
    en_obj.canonical_name,
    en_obj.node_type
ORDER BY
    max_weight DESC;

-- Unique index required for CONCURRENT refresh
CREATE UNIQUE INDEX IF NOT EXISTS idx_student_summary_pk
ON student_learning_summary (tenant_id, predicate, concept);

-- ── Row-level security (RLS) policies ───────────────────────
-- Enable RLS so each tenant only sees their own data.
-- Works with Supabase's built-in auth.uid() → tenant_id mapping.

ALTER TABLE entity_nodes      ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_aliases    ENABLE ROW LEVEL SECURITY;
ALTER TABLE relation_edges    ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunks  ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_turns ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS (used by FastAPI backend)
-- App role uses RLS (used by Supabase JS client if called directly)

-- Example policy (customize for your auth setup):
-- CREATE POLICY tenant_isolation ON entity_nodes
--     USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- ── FUNCTION: Decay edge weights over time ───────────────────
-- Run as a nightly cron job via pg_cron or Supabase edge function.
-- Edges that haven't been reinforced naturally fade (Ebbinghaus forgetting curve).
CREATE OR REPLACE FUNCTION decay_edge_weights(
    p_decay_factor FLOAT DEFAULT 0.95,    -- multiply weight by this each day
    p_min_weight   FLOAT DEFAULT 0.1,     -- never go below this
    p_days_idle    INT   DEFAULT 7        -- only decay if not updated in N days
)
RETURNS INT   -- number of edges decayed
LANGUAGE plpgsql
AS $$
DECLARE
    affected INT;
BEGIN
    UPDATE relation_edges
    SET    weight     = GREATEST(weight * p_decay_factor, p_min_weight),
           updated_at = NOW()
    WHERE  updated_at < NOW() - (p_days_idle || ' days')::INTERVAL
      AND  weight > p_min_weight;

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;
