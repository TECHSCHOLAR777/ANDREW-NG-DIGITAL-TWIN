-- ============================================================
-- Migration 011: Tenant Isolation
--
-- Two problems, both of which were "safe by accident" rather than
-- safe by construction.
--
-- 1. RLS THEATRE.
--    Migration 004 ran ALTER TABLE ... ENABLE ROW LEVEL SECURITY on
--    five tables and defined ZERO policies, leaving only a commented
--    out example. Enabling RLS with no policies means the tables are
--    closed to ordinary roles and wide open to the service role the
--    backend connects with, so the net effect was decorative: it
--    looks like isolation in a code review and enforces nothing.
--
--    Real policies are added here, keyed off a session GUC
--    (app.tenant_id). They only bite for non-superuser roles, so the
--    existing service-role backend keeps working unchanged, but the
--    door is now open to running the app on a restricted role, and
--    to using Supabase client libraries directly.
--
-- 2. "SHARED CORPUS" MEANT "EVERY TENANT'S CHUNKS".
--    hybrid_chunk_retrieval treats p_tenant_id IS NULL as "no tenant
--    filter at all". Today only the corpus tenant writes
--    knowledge_chunks, so that happens to be correct. The moment any
--    feature lets a user upload their own notes, an unset
--    CORPUS_TENANT_ID would serve user A's private documents to user
--    B. NULL as a wildcard is the wrong way to express "shared".
--
--    An explicit is_shared flag replaces the accident.
-- ============================================================

-- ── 1. Explicit shared-corpus flag ──────────────────────────
ALTER TABLE knowledge_chunks
    ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN knowledge_chunks.is_shared IS
    'TRUE = part of the public Andrew corpus, readable by every tenant. '
    'FALSE = private to owning tenant_id (user uploads). Retrieval must '
    'never mix the two without an explicit tenant match.';

-- Everything ingested so far is the shared Andrew corpus.
UPDATE knowledge_chunks SET is_shared = TRUE WHERE is_shared IS DISTINCT FROM TRUE;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_shared
    ON knowledge_chunks (is_shared, tenant_id);


-- ── Retrieval respects the flag ─────────────────────────────
-- p_tenant_id now means "the caller", not "the corpus owner". A row is
-- visible when it is shared corpus material OR privately owned by the
-- caller. Passing NULL still works and yields shared material only,
-- which is a safe default rather than a wildcard.
CREATE OR REPLACE FUNCTION hybrid_chunk_retrieval(
    p_tenant_id       UUID,
    p_query_embedding VECTOR(768),
    p_query_text      TEXT,
    p_top_k           INT   DEFAULT 10,
    p_rrf_k           INT   DEFAULT 60,
    p_vector_weight   FLOAT DEFAULT 0.65,
    p_fts_weight      FLOAT DEFAULT 0.35,
    p_source_types    TEXT[] DEFAULT NULL
)
RETURNS TABLE (
    chunk_id        UUID,
    source_file     TEXT,
    source_type     TEXT,
    chunk_text      TEXT,
    chunk_index     INT,
    authority_prior FLOAT,
    vector_rank     INT,
    fts_rank        INT,
    vector_score    FLOAT,
    fts_score       FLOAT,
    rrf_score       FLOAT,
    final_score     FLOAT
)
LANGUAGE sql STABLE
AS $$
WITH
visible AS (
    SELECT *
    FROM   knowledge_chunks kc
    WHERE  (kc.is_shared OR (p_tenant_id IS NOT NULL AND kc.tenant_id = p_tenant_id))
      AND  (p_source_types IS NULL OR kc.source_type = ANY(p_source_types))
),
vector_results AS (
    SELECT
        id AS chunk_id,
        1 - (embedding <=> p_query_embedding) AS cos_sim,
        ROW_NUMBER() OVER (ORDER BY embedding <=> p_query_embedding) AS vec_rank
    FROM visible
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> p_query_embedding
    LIMIT (p_top_k * 4)
),
fts_query AS (
    SELECT plainto_tsquery('english', p_query_text) AS tsq
),
fts_results AS (
    SELECT
        v.id AS chunk_id,
        ts_rank_cd(v.fts_document, fq.tsq, 32) AS ts_score,
        ROW_NUMBER() OVER (ORDER BY ts_rank_cd(v.fts_document, fq.tsq, 32) DESC) AS fts_rank
    FROM visible v, fts_query fq
    WHERE v.fts_document @@ fq.tsq
    ORDER BY ts_score DESC
    LIMIT (p_top_k * 4)
),
rrf_fusion AS (
    SELECT
        COALESCE(vr.chunk_id, fr.chunk_id) AS chunk_id,
        COALESCE(vr.vec_rank, (p_top_k * 4) + 1)::INT AS v_rank,
        COALESCE(fr.fts_rank, (p_top_k * 4) + 1)::INT AS f_rank,
        COALESCE(vr.cos_sim, 0.0) AS cos_sim,
        COALESCE(fr.ts_score, 0.0) AS ts_score,
        (
            p_vector_weight * (1.0 / (p_rrf_k + COALESCE(vr.vec_rank, (p_top_k * 4) + 1)))
          + p_fts_weight    * (1.0 / (p_rrf_k + COALESCE(fr.fts_rank, (p_top_k * 4) + 1)))
        ) AS rrf_score
    FROM vector_results vr
    FULL OUTER JOIN fts_results fr USING (chunk_id)
)
SELECT
    kc.id, kc.source_file, kc.source_type, kc.chunk_text, kc.chunk_index,
    kc.authority_prior, rf.v_rank, rf.f_rank, rf.cos_sim, rf.ts_score,
    rf.rrf_score,
    rf.rrf_score * kc.authority_prior AS final_score
FROM rrf_fusion rf
JOIN knowledge_chunks kc ON kc.id = rf.chunk_id
ORDER BY final_score DESC
LIMIT p_top_k;
$$;


-- Neighbour expansion must obey the same visibility rule, or a private
-- chunk could be pulled in as a "neighbour" of a shared one.
CREATE OR REPLACE FUNCTION fetch_chunk_neighbors(
    p_tenant_id UUID,
    p_chunk_ids UUID[],
    p_window    INT DEFAULT 1
)
RETURNS TABLE (
    chunk_id        UUID,
    source_file     TEXT,
    source_type     TEXT,
    chunk_text      TEXT,
    chunk_index     INT,
    authority_prior FLOAT
)
LANGUAGE sql STABLE
AS $$
WITH visible AS (
    SELECT *
    FROM   knowledge_chunks kc
    WHERE  (kc.is_shared OR (p_tenant_id IS NOT NULL AND kc.tenant_id = p_tenant_id))
),
seeds AS (
    SELECT v.source_file, v.chunk_index
    FROM   visible v
    WHERE  v.id = ANY(p_chunk_ids)
),
wanted AS (
    SELECT DISTINCT s.source_file, g.idx
    FROM   seeds s,
           LATERAL generate_series(s.chunk_index - p_window, s.chunk_index + p_window) AS g(idx)
)
SELECT v.id, v.source_file, v.source_type, v.chunk_text, v.chunk_index, v.authority_prior
FROM   visible v
JOIN   wanted w ON w.source_file = v.source_file AND w.idx = v.chunk_index
ORDER BY v.source_file, v.chunk_index;
$$;


-- ── 2. Real row level security policies ─────────────────────
-- Tenant identity comes from a per-session setting the application
-- sets after authenticating. Until SEC-02 lands the backend runs as
-- the service role and bypasses all of this, so these policies are
-- inert today. They are written now so that the switch to a
-- restricted role is a configuration change, not a schema project.

CREATE OR REPLACE FUNCTION current_tenant_id()
RETURNS UUID
LANGUAGE sql STABLE
AS $$
    SELECT NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid;
$$;

ALTER TABLE entity_nodes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_aliases     ENABLE ROW LEVEL SECURITY;
ALTER TABLE relation_edges     ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunks   ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions      ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON entity_nodes;
CREATE POLICY tenant_isolation ON entity_nodes
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation ON entity_aliases;
CREATE POLICY tenant_isolation ON entity_aliases
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation ON relation_edges;
CREATE POLICY tenant_isolation ON relation_edges
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation ON conversation_turns;
CREATE POLICY tenant_isolation ON conversation_turns
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP POLICY IF EXISTS tenant_isolation ON chat_sessions;
CREATE POLICY tenant_isolation ON chat_sessions
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- Shared corpus is readable by everyone; private chunks only by owner.
-- Writes always require ownership.
DROP POLICY IF EXISTS corpus_read ON knowledge_chunks;
CREATE POLICY corpus_read ON knowledge_chunks
    FOR SELECT
    USING (is_shared OR tenant_id = current_tenant_id());

DROP POLICY IF EXISTS corpus_write ON knowledge_chunks;
CREATE POLICY corpus_write ON knowledge_chunks
    FOR ALL
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());
