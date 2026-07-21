-- ============================================================
-- Migration 009: Temporal Belief Graph
--
-- Three problems fixed:
--
-- 1. NULLABLE session_id DEFEATED THE UNIQUE CONSTRAINT.
--    Migration 005 added session_id to the SPO uniqueness key but
--    left it nullable, and Postgres treats NULLs as distinct. Any
--    edge with a NULL session could be inserted without limit and
--    its ON CONFLICT clause never fired, so weight accumulation
--    silently stopped working for those rows. Migration 005's own
--    comment noticed this and shipped anyway.
--
-- 2. THE GRAPH COULD NOT CHANGE ITS MIND.
--    A student who struggles with backprop in January and masters
--    it in March ended up with BOTH edges, both alive, both fed to
--    the prompt, with nothing indicating which was current. The
--    longer someone used the system the more contradictory its
--    memory became. `weight` could not express this because it was
--    already overloaded: extraction confidence, evidence strength
--    and currency all crammed into one float.
--
-- 3. EDGES ACCUMULATED FOREVER.
--    decay_edge_weights() existed, was documented with an
--    Ebbinghaus rationale, and was never called by anything.
--
-- The fix is bi-temporal edges: valid_from records when we came to
-- believe something, invalidated_at records when we stopped. Reads
-- filter on invalidated_at IS NULL for current belief; history
-- stays queryable for trajectory ("you struggled with this in
-- January and it clicked in March"), which is the sentence a real
-- mentor says and which the old schema could not produce at any
-- prompt-engineering effort.
-- ============================================================

-- ── 1. Sentinel session for non-session-scoped edges ────────
-- Curriculum edges (concept-to-concept structure extracted from the
-- corpus rather than from a chat) belong to no session. Rather than
-- reintroducing NULL, they use an all-zero sentinel so uniqueness
-- keeps working.
UPDATE relation_edges
SET    session_id = '00000000-0000-0000-0000-000000000000'::uuid
WHERE  session_id IS NULL;

ALTER TABLE relation_edges
    ALTER COLUMN session_id SET DEFAULT '00000000-0000-0000-0000-000000000000'::uuid;

ALTER TABLE relation_edges
    ALTER COLUMN session_id SET NOT NULL;


-- ── 2. Temporal validity columns ────────────────────────────
ALTER TABLE relation_edges
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE relation_edges
    ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;

-- Why the edge stopped being believed (audit trail, and useful in
-- the UI: "superseded when you said it finally clicked")
ALTER TABLE relation_edges
    ADD COLUMN IF NOT EXISTS invalidated_reason TEXT;

-- Split the overloaded weight column. `weight` keeps its meaning as
-- the ranking signal; observation_count records how many times a
-- belief was independently reasserted, which is what "this student
-- REALLY struggles with X" actually means.
ALTER TABLE relation_edges
    ADD COLUMN IF NOT EXISTS observation_count INT NOT NULL DEFAULT 1;


-- ── 3. Uniqueness over LIVE edges only ──────────────────────
-- A table-level constraint cannot be partial, so the constraint is
-- replaced with a partial unique index. This allows unlimited
-- historical (invalidated) rows for the same triple while still
-- guaranteeing at most one live edge per (tenant, session, S, P, O).
-- Without the partial predicate, re-asserting a previously
-- invalidated belief would collide with the dead row and resurrect
-- it instead of creating a new one.
ALTER TABLE relation_edges
    DROP CONSTRAINT IF EXISTS uq_relation_edges_spo;

DROP INDEX IF EXISTS uq_relation_edges_spo_live;

CREATE UNIQUE INDEX uq_relation_edges_spo_live
    ON relation_edges (tenant_id, session_id, subject_id, predicate, object_id)
    WHERE invalidated_at IS NULL;

-- Fast lookup of a tenant's current belief set
CREATE INDEX IF NOT EXISTS idx_relation_edges_live
    ON relation_edges (tenant_id, subject_id, object_id)
    WHERE invalidated_at IS NULL;


-- ============================================================
-- FUNCTION: opposing_predicates
-- Which beliefs are contradicted by asserting p_predicate.
--
-- Invalidation is deliberately symmetric. People regress: a student
-- who mastered something in January and is confused about it in
-- June should have the stale mastery retired, not have the new
-- confusion rejected because mastery ranks "higher". Treating
-- learning as monotonic is exactly the modelling error that makes
-- tutoring systems feel like they are not listening.
-- ============================================================
CREATE OR REPLACE FUNCTION opposing_predicates(p_predicate TEXT)
RETURNS TEXT[]
LANGUAGE sql IMMUTABLE
AS $$
    SELECT CASE p_predicate
        WHEN 'mastered'        THEN ARRAY['struggles_with', 'confused_about', 'wants_to_learn']
        WHEN 'struggles_with'  THEN ARRAY['mastered']
        WHEN 'confused_about'  THEN ARRAY['mastered']
        WHEN 'studied'         THEN ARRAY[]::TEXT[]
        ELSE ARRAY[]::TEXT[]
    END;
$$;


-- ============================================================
-- FUNCTION: invalidate_opposing_edges
-- Retire live beliefs that the incoming assertion contradicts.
-- Scoped to the whole tenant, not one session: a belief formed in
-- last week's conversation is exactly the thing today's
-- conversation should be able to supersede.
-- ============================================================
CREATE OR REPLACE FUNCTION invalidate_opposing_edges(
    p_tenant_id  UUID,
    p_subject_id UUID,
    p_object_id  UUID,
    p_predicate  TEXT,
    p_reason     TEXT DEFAULT NULL
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
    v_opposing TEXT[];
    v_count    INT;
BEGIN
    v_opposing := opposing_predicates(p_predicate);
    IF array_length(v_opposing, 1) IS NULL THEN
        RETURN 0;
    END IF;

    UPDATE relation_edges
    SET    invalidated_at     = NOW(),
           invalidated_reason = COALESCE(p_reason, 'superseded by ' || p_predicate)
    WHERE  tenant_id      = p_tenant_id
      AND  subject_id     = p_subject_id
      AND  object_id      = p_object_id
      AND  predicate      = ANY(v_opposing)
      AND  invalidated_at IS NULL;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;


-- ============================================================
-- FUNCTION: invalidate_edge_by_id
-- Explicit retraction, used by the "this is wrong" control in the
-- UI and by the extractor's `invalidate` operation.
--
-- Soft delete rather than DELETE: a student correcting the graph is
-- the cheapest labelled data available for evaluating the
-- extraction prompt, and throwing the row away throws that away.
-- ============================================================
CREATE OR REPLACE FUNCTION invalidate_edge_by_id(
    p_tenant_id UUID,
    p_edge_id   UUID,
    p_reason    TEXT DEFAULT 'corrected by student'
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_found BOOLEAN;
BEGIN
    UPDATE relation_edges
    SET    invalidated_at     = NOW(),
           invalidated_reason = p_reason
    WHERE  id             = p_edge_id
      AND  tenant_id      = p_tenant_id
      AND  invalidated_at IS NULL
    RETURNING TRUE INTO v_found;

    RETURN COALESCE(v_found, FALSE);
END;
$$;


-- ============================================================
-- Rebuild traversal and decay to respect temporal validity.
-- Signatures unchanged so callers need no edits.
-- ============================================================
CREATE OR REPLACE FUNCTION graph_2hop_traversal(
    p_tenant_id   UUID,
    p_anchor_ids  UUID[],
    p_predicates  TEXT[] DEFAULT NULL,
    p_max_nodes   INT  DEFAULT 50,
    p_session_id  UUID DEFAULT NULL
)
RETURNS TABLE (
    node_id        UUID,
    canonical_name TEXT,
    node_type      TEXT,
    metadata       JSONB,
    hop_distance   INT,
    path_weight    FLOAT,
    predicates_path TEXT[]
)
LANGUAGE sql STABLE
AS $$
WITH RECURSIVE
traversal(node_id, hop_distance, path_weight, predicates_path, visited) AS (
    SELECT
        unnest(p_anchor_ids)    AS node_id,
        0                       AS hop_distance,
        1.0::double precision   AS path_weight,
        ARRAY[]::TEXT[]         AS predicates_path,
        p_anchor_ids            AS visited

    UNION ALL

    -- Undirected expansion (migration 007) now also filtered to
    -- currently-believed edges only.
    SELECT
        CASE WHEN re.subject_id = t.node_id THEN re.object_id ELSE re.subject_id END,
        t.hop_distance + 1,
        t.path_weight * re.weight * 0.85,
        t.predicates_path || re.predicate,
        t.visited || (CASE WHEN re.subject_id = t.node_id THEN re.object_id ELSE re.subject_id END)
    FROM traversal t
    JOIN relation_edges re
        ON  re.tenant_id = p_tenant_id
        AND (re.subject_id = t.node_id OR re.object_id = t.node_id)
        AND re.invalidated_at IS NULL
        AND (p_predicates IS NULL OR re.predicate = ANY(p_predicates))
        AND (p_session_id IS NULL OR re.session_id = p_session_id)
    WHERE
        t.hop_distance < 2
        AND NOT ((CASE WHEN re.subject_id = t.node_id THEN re.object_id ELSE re.subject_id END) = ANY(t.visited))
        AND t.path_weight * re.weight > 0.05
)
SELECT DISTINCT ON (en.id)
    en.id, en.canonical_name, en.node_type, en.metadata,
    t.hop_distance, t.path_weight, t.predicates_path
FROM traversal t
JOIN entity_nodes en
    ON en.id = t.node_id AND en.tenant_id = p_tenant_id
ORDER BY en.id, t.path_weight DESC
LIMIT p_max_nodes;
$$;


-- Decay only touches live edges now. An invalidated belief should
-- keep the weight it had when it was retired, so history stays
-- readable rather than fading to a floor value.
CREATE OR REPLACE FUNCTION decay_edge_weights(
    p_decay_factor FLOAT DEFAULT 0.95,
    p_min_weight   FLOAT DEFAULT 0.1,
    p_days_idle    INT   DEFAULT 7
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
    affected INT;
BEGIN
    UPDATE relation_edges
    SET    weight     = GREATEST(weight * p_decay_factor, p_min_weight),
           updated_at = NOW()
    WHERE  updated_at < NOW() - (p_days_idle || ' days')::INTERVAL
      AND  weight > p_min_weight
      AND  invalidated_at IS NULL;

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;

-- ── Scheduling the decay ────────────────────────────────────
-- decay_edge_weights() has never been called by anything. Enable
-- pg_cron in the Supabase dashboard and run this once:
--
--   SELECT cron.schedule(
--       'decay-edges-nightly', '0 3 * * *',
--       $cron$ SELECT decay_edge_weights(); $cron$
--   );
--
-- If pg_cron is unavailable, the backend calls it opportunistically
-- at most once per hour (see maybe_run_decay in graph_memory.py).


-- ============================================================
-- VIEW: current_beliefs
-- Convenience view so application code cannot forget the temporal
-- filter. Any read that wants "what is true now" should use this.
-- ============================================================
CREATE OR REPLACE VIEW current_beliefs AS
SELECT *
FROM   relation_edges
WHERE  invalidated_at IS NULL;
