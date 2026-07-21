-- ============================================================
-- Migration 006: Shared Corpus Retrieval
-- Lets runtime query the Andrew knowledge corpus independently
-- from private user-memory tenants.
-- ============================================================

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
vector_results AS (
    SELECT
        id AS chunk_id,
        1 - (embedding <=> p_query_embedding) AS cos_sim,
        ROW_NUMBER() OVER (ORDER BY embedding <=> p_query_embedding) AS vec_rank
    FROM knowledge_chunks
    WHERE (p_tenant_id IS NULL OR tenant_id = p_tenant_id)
      AND embedding IS NOT NULL
      AND (p_source_types IS NULL OR source_type = ANY(p_source_types))
    ORDER BY embedding <=> p_query_embedding
    LIMIT (p_top_k * 4)
),
fts_query AS (
    SELECT plainto_tsquery('english', p_query_text) AS tsq
),
fts_results AS (
    SELECT
        kc.id AS chunk_id,
        ts_rank_cd(kc.fts_document, fq.tsq, 32) AS ts_score,
        ROW_NUMBER() OVER (ORDER BY ts_rank_cd(kc.fts_document, fq.tsq, 32) DESC) AS fts_rank
    FROM knowledge_chunks kc, fts_query fq
    WHERE (p_tenant_id IS NULL OR kc.tenant_id = p_tenant_id)
      AND kc.fts_document @@ fq.tsq
      AND (p_source_types IS NULL OR kc.source_type = ANY(p_source_types))
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
    kc.id AS chunk_id,
    kc.source_file,
    kc.source_type,
    kc.chunk_text,
    kc.chunk_index,
    kc.authority_prior,
    rf.v_rank AS vector_rank,
    rf.f_rank AS fts_rank,
    rf.cos_sim AS vector_score,
    rf.ts_score AS fts_score,
    rf.rrf_score,
    rf.rrf_score * kc.authority_prior AS final_score
FROM rrf_fusion rf
JOIN knowledge_chunks kc
    ON kc.id = rf.chunk_id
   AND (p_tenant_id IS NULL OR kc.tenant_id = p_tenant_id)
ORDER BY final_score DESC
LIMIT p_top_k;
$$;
