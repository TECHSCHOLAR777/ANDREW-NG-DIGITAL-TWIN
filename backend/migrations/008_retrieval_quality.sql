-- ============================================================
-- Migration 008: Retrieval Quality
--
-- Two changes:
--   1. Replace IVFFlat vector indexes with HNSW.
--   2. Add fetch_chunk_neighbors() for neighbour expansion.
--
-- ── Why HNSW ────────────────────────────────────────────────
-- Migration 001 created IVFFlat indexes at schema-creation time,
-- BEFORE any rows were ingested. IVFFlat clusters the existing
-- vectors into `lists` partitions when the index is built and
-- then probes only the nearest few at query time. Built against
-- an empty table there is nothing to cluster, so the partitioning
-- does not reflect the data and recall degrades — silently, with
-- no error and no failed query.
--
-- HNSW builds a navigable graph incrementally as rows arrive, so
-- it has no training step and no empty-table failure mode. It
-- also gives better recall at equivalent speed for corpora of
-- this size. The tradeoffs (slower inserts, more memory) do not
-- matter for a corpus ingested once and then read.
--
-- Requires pgvector >= 0.5.0. Supabase ships a newer version.
--
-- NOTE: building these indexes takes time proportional to row
-- count. For a corpus of a few thousand chunks this is seconds.
-- ============================================================

-- ── Knowledge chunks: drop IVFFlat, build HNSW ──────────────
DROP INDEX IF EXISTS idx_knowledge_chunks_embedding;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_hnsw
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ── Entity nodes: same treatment ────────────────────────────
DROP INDEX IF EXISTS idx_entity_nodes_embedding;

CREATE INDEX IF NOT EXISTS idx_entity_nodes_embedding_hnsw
    ON entity_nodes USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ── Supporting index for neighbour lookups ──────────────────
-- fetch_chunk_neighbors joins on (source_file, chunk_index);
-- without this it degenerates into a sequential scan per call.
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_file_index
    ON knowledge_chunks (tenant_id, source_file, chunk_index);


-- ============================================================
-- FUNCTION: fetch_chunk_neighbors
--
-- Given the chunk ids that survived ranking, return those chunks
-- plus their immediate neighbours (chunk_index ± p_window) from
-- the same source file.
--
-- Why this exists: chunks were ingested as ~1000 character
-- paragraph packs with NO overlap. Lecture notes are sequentially
-- dependent — chunk 47 uses notation chunk 46 introduced. A hit
-- returned alone frequently lacks the definition it relies on,
-- and the model then fills the gap from its own parametric
-- knowledge, producing a fluent answer that is not actually
-- grounded. That failure is invisible in the output, which is
-- what makes it dangerous.
--
-- Returns rows in (source_file, chunk_index) order so the caller
-- can merge contiguous runs into single passages.
-- ============================================================
CREATE OR REPLACE FUNCTION fetch_chunk_neighbors(
    p_tenant_id UUID,          -- NULL = shared corpus
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
WITH seeds AS (
    SELECT kc.source_file, kc.chunk_index
    FROM   knowledge_chunks kc
    WHERE  kc.id = ANY(p_chunk_ids)
      AND  (p_tenant_id IS NULL OR kc.tenant_id = p_tenant_id)
),
wanted AS (
    SELECT DISTINCT s.source_file, g.idx
    FROM   seeds s,
           LATERAL generate_series(
               s.chunk_index - p_window,
               s.chunk_index + p_window
           ) AS g(idx)
)
SELECT
    kc.id,
    kc.source_file,
    kc.source_type,
    kc.chunk_text,
    kc.chunk_index,
    kc.authority_prior
FROM   knowledge_chunks kc
JOIN   wanted w
    ON w.source_file = kc.source_file
   AND w.idx         = kc.chunk_index
WHERE  (p_tenant_id IS NULL OR kc.tenant_id = p_tenant_id)
ORDER BY kc.source_file, kc.chunk_index;
$$;
