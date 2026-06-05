-- ============================================================
-- Migration 003: Dual-Path Hybrid Retrieval with RRF
-- Fuses pgvector ANN + PostgreSQL FTS using Reciprocal Rank Fusion
-- with custom source authority priors.
-- ============================================================

-- ============================================================
-- FUNCTION: hybrid_chunk_retrieval
-- Single SQL query replacing Chroma + BM25 entirely.
--
-- Reciprocal Rank Fusion formula:
--   RRF(d) = Σ 1 / (k + rank(d))   where k=60 (standard constant)
--
-- Authority prior multiplier boosts high-quality sources:
--   lecture=1.0, paper=0.8, newsletter=0.5, qa=0.3
--
-- Final score = RRF_score × authority_prior
--
-- Parameters:
--   p_query_embedding  : pre-computed vector from text-embedding-004
--   p_query_text       : raw query string for FTS
--   p_tenant_id        : tenant scope
--   p_top_k            : number of results to return
--   p_rrf_k            : RRF constant (default 60, standard)
--   p_vector_weight    : weight for vector path (0-1)
--   p_fts_weight       : weight for FTS path (0-1)
--   p_source_types     : optional filter (e.g. ARRAY['lecture','paper'])
-- ============================================================
CREATE OR REPLACE FUNCTION hybrid_chunk_retrieval(
    p_tenant_id       UUID,
    p_query_embedding VECTOR(768),
    p_query_text      TEXT,
    p_top_k           INT   DEFAULT 10,
    p_rrf_k           INT   DEFAULT 60,
    p_vector_weight   FLOAT DEFAULT 0.65,    -- slightly favour semantic
    p_fts_weight      FLOAT DEFAULT 0.35,
    p_source_types    TEXT[] DEFAULT NULL    -- NULL = all source types
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
    vector_score    FLOAT,   -- raw cosine similarity
    fts_score       FLOAT,   -- raw ts_rank
    rrf_score       FLOAT,   -- fused pre-authority
    final_score     FLOAT    -- rrf × authority_prior
)
LANGUAGE sql STABLE
AS $$
WITH

-- ── PATH 1: Vector Similarity (pgvector ANN) ─────────────────
vector_results AS (
    SELECT
        id                                              AS chunk_id,
        1 - (embedding <=> p_query_embedding)           AS cos_sim,
        ROW_NUMBER() OVER (
            ORDER BY embedding <=> p_query_embedding    -- nearest first
        )                                               AS vec_rank
    FROM  knowledge_chunks
    WHERE tenant_id = p_tenant_id
      AND embedding IS NOT NULL
      AND (p_source_types IS NULL OR source_type = ANY(p_source_types))
    ORDER BY embedding <=> p_query_embedding
    LIMIT (p_top_k * 4)   -- oversample for fusion; RRF re-ranks
),

-- ── PATH 2: Full-Text Search (PostgreSQL native BM25-like) ───
fts_query AS (
    -- Convert raw text to a tsquery with phrase-then-fallback strategy:
    -- 1. Try exact phrase query (highest precision)
    -- 2. Fall back to OR of individual terms (higher recall)
    SELECT
        COALESCE(
            to_tsquery('english', replace(
                trim(regexp_replace(regexp_replace(p_query_text, '[^a-zA-Z0-9 ]', ' ', 'g'), ' {2,}', ' ', 'g')),
                ' ', ' & '
            )),
            plainto_tsquery('english', p_query_text)
        ) AS tsq
),

fts_results AS (
    SELECT
        kc.id                                           AS chunk_id,
        ts_rank_cd(kc.fts_document, fq.tsq, 32)        AS ts_score,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(kc.fts_document, fq.tsq, 32) DESC
        )                                               AS fts_rank
    FROM  knowledge_chunks kc, fts_query fq
    WHERE kc.tenant_id = p_tenant_id
      AND kc.fts_document @@ fq.tsq
      AND (p_source_types IS NULL OR kc.source_type = ANY(p_source_types))
    ORDER BY ts_score DESC
    LIMIT (p_top_k * 4)
),

-- ── FUSION: Reciprocal Rank Fusion ───────────────────────────
-- FULL OUTER JOIN to capture docs that appear in only one path.
-- Missing rank → treated as (max_rank + 1) for RRF denominator.
rrf_fusion AS (
    SELECT
        COALESCE(vr.chunk_id, fr.chunk_id)  AS chunk_id,
        COALESCE(vr.vec_rank, (p_top_k * 4) + 1)::INT  AS v_rank,
        COALESCE(fr.fts_rank, (p_top_k * 4) + 1)::INT  AS f_rank,
        COALESCE(vr.cos_sim,  0.0)          AS cos_sim,
        COALESCE(fr.ts_score, 0.0)          AS ts_score,

        -- Weighted RRF score
        (
            p_vector_weight * (1.0 / (p_rrf_k + COALESCE(vr.vec_rank, (p_top_k * 4) + 1)))
          + p_fts_weight    * (1.0 / (p_rrf_k + COALESCE(fr.fts_rank, (p_top_k * 4) + 1)))
        )                                   AS rrf_score
    FROM       vector_results vr
    FULL OUTER JOIN fts_results fr USING (chunk_id)
)

-- ── FINAL: Join metadata, apply authority prior ───────────────
SELECT
    kc.id               AS chunk_id,
    kc.source_file,
    kc.source_type,
    kc.chunk_text,
    kc.chunk_index,
    kc.authority_prior,
    rf.v_rank           AS vector_rank,
    rf.f_rank           AS fts_rank,
    rf.cos_sim          AS vector_score,
    rf.ts_score         AS fts_score,
    rf.rrf_score,
    -- Authority prior applied as a multiplicative boost
    rf.rrf_score * kc.authority_prior AS final_score
FROM
    rrf_fusion rf
    JOIN knowledge_chunks kc
        ON kc.id = rf.chunk_id
        AND kc.tenant_id = p_tenant_id
ORDER BY
    final_score DESC
LIMIT p_top_k;
$$;


-- ============================================================
-- AUTHORITY PRIOR HELPER
-- Automatically sets the authority_prior on insert based on source_type.
-- Saves Python callers from having to pass it manually.
-- ============================================================
CREATE OR REPLACE FUNCTION set_authority_prior()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.authority_prior := CASE NEW.source_type
        WHEN 'lecture'    THEN 1.0
        WHEN 'paper'      THEN 0.8
        WHEN 'qa'         THEN 0.6
        WHEN 'newsletter' THEN 0.5
        ELSE 0.4
    END;
    RETURN NEW;
END;
$$;

-- Only set the prior if the caller didn't override it
CREATE TRIGGER trg_set_authority_prior
BEFORE INSERT ON knowledge_chunks
FOR EACH ROW
WHEN (NEW.authority_prior = 1.0 AND NEW.source_type <> 'lecture')
EXECUTE FUNCTION set_authority_prior();


-- ============================================================
-- VIEW: Convenient query interface for Python
-- Usage from Python:
--   SELECT * FROM hybrid_retrieve($1,$2,$3) LIMIT 10;
-- ============================================================
CREATE OR REPLACE VIEW retrieval_usage_example AS
-- This is documentation-only; not meant to be queried directly.
-- From Python/FastAPI:
--
--   rows = await db.fetch("""
--       SELECT * FROM hybrid_chunk_retrieval(
--           $1,   -- tenant_id UUID
--           $2,   -- query_embedding vector(768)
--           $3,   -- query_text text
--           10,   -- top_k
--           60,   -- rrf_k
--           0.65, -- vector_weight
--           0.35  -- fts_weight
--       )
--   """, tenant_id, embedding, query_text)
SELECT 'See comment above for usage' AS note;
