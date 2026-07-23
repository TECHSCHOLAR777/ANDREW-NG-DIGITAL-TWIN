-- ============================================================
-- Migration 014: Move embeddings to voyage-4-lite (1024-dim)
--
-- WHY
-- The Gemini free embedding tier caps at ~1000 texts/day, which
-- turns a 14k-chunk corpus into a week of daily runs. Voyage AI
-- gives 200M free tokens, so the whole corpus embeds in one pass.
-- Its smallest lite model emits 1024 dimensions (256/512/2048 are
-- the other options; 768 is not offered), so the vector columns
-- move from 768 to 1024.
--
-- SAFE BECAUSE THE FUNCTIONS ARE DIMENSIONLESS
-- The retrieval functions (hybrid_chunk_retrieval,
-- vector_anchored_subgraph) declare their parameter as bare
-- `vector`, not `vector(768)`, so they accept any dimension at
-- runtime and need no change here. Only the stored columns and
-- their HNSW indexes are dimension-bound.
--
-- VECTORS ARE NOT CONVERTIBLE
-- A 768-dim Gemini vector cannot be reshaped into a 1024-dim
-- Voyage one; they are different spaces. So the existing chunk
-- embeddings are cleared and the corpus is re-embedded from
-- source. The provenance column (013) then relabels every row as
-- voyage, and the ingest's mixing guard keeps it single-model.
-- ============================================================

-- 1. Drop the dimension-bound indexes before altering the columns.
DROP INDEX IF EXISTS idx_knowledge_chunks_embedding_hnsw;
DROP INDEX IF EXISTS idx_entity_nodes_embedding_hnsw;

-- 2. Clear the old vectors. A dimension change is refused while any
--    value of the old dimension remains.
--
--    knowledge_chunks is fully rebuilt from source on the next ingest,
--    so its rows are removed outright rather than just nulled: that also
--    resets the ingest's "already loaded" bookkeeping cleanly.
DELETE FROM knowledge_chunks;

--    entity_nodes are built at runtime from conversations. Any existing
--    embeddings are nulled (the nodes themselves are kept); they are
--    re-embedded the next time the graph touches them.
UPDATE entity_nodes SET embedding = NULL WHERE embedding IS NOT NULL;

-- 3. Move the columns to 1024.
ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE entity_nodes     ALTER COLUMN embedding TYPE vector(1024);

-- 4. Recreate the HNSW indexes at the new dimension. They build instantly
--    now (the tables are empty of vectors); for knowledge_chunks the index
--    is best rebuilt once more after the corpus is loaded, so its graph is
--    formed over settled data rather than incrementally. See the ingest
--    runbook's REINDEX step.
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_hnsw
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_entity_nodes_embedding_hnsw
    ON entity_nodes USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 5. Relabel provenance. Rows arriving from here are voyage; the ingest
--    sets this per row, and this default keeps any in-flight insert honest.
ALTER TABLE knowledge_chunks
    ALTER COLUMN embedding_model SET DEFAULT 'voyage:voyage-4-lite';
