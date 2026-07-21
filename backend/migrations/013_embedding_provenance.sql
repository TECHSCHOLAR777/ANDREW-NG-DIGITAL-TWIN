-- ============================================================
-- Migration 013: Embedding Provenance
--
-- THE FAILURE THIS PREVENTS
-- Vectors from different models are not comparable. Cosine
-- similarity between an all-mpnet-base-v2 vector and a
-- gemini-embedding-001 vector is a meaningless number, not an
-- error.
--
-- Both models emit 768 dimensions. The column type is VECTOR(768)
-- either way, so mixing them does not violate the schema, does not
-- raise, and does not log anything. Retrieval simply returns
-- irrelevant passages, the tutor answers fluently from them, and
-- nothing anywhere indicates a problem.
--
-- That is the worst class of bug in this system: silent, plausible
-- output. Recording which model produced each vector turns it into
-- something the ingest script can refuse to do.
-- ============================================================

ALTER TABLE knowledge_chunks
    ADD COLUMN IF NOT EXISTS embedding_model TEXT;

ALTER TABLE entity_nodes
    ADD COLUMN IF NOT EXISTS embedding_model TEXT;

COMMENT ON COLUMN knowledge_chunks.embedding_model IS
    'Provider and model that produced `embedding`, e.g. '
    '"gemini:models/gemini-embedding-001". Vectors from different models are '
    'not comparable; the ingest script refuses to mix them.';

-- Anything already present came from the current run. A corpus built before
-- this migration existed is labelled unknown rather than guessed at.
UPDATE knowledge_chunks
SET    embedding_model = COALESCE(embedding_model, 'unknown')
WHERE  embedding IS NOT NULL AND embedding_model IS NULL;

UPDATE entity_nodes
SET    embedding_model = COALESCE(embedding_model, 'unknown')
WHERE  embedding IS NOT NULL AND embedding_model IS NULL;

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_model
    ON knowledge_chunks (embedding_model);


-- ============================================================
-- FUNCTION: corpus_embedding_models
-- Which models are represented in the corpus right now.
--
-- More than one row is a problem: it means the corpus is a mix and
-- retrieval quality is silently degraded for whichever portion does
-- not match the query-time model.
-- ============================================================
CREATE OR REPLACE FUNCTION corpus_embedding_models()
RETURNS TABLE (embedding_model TEXT, chunks BIGINT)
LANGUAGE sql STABLE
AS $$
    SELECT COALESCE(kc.embedding_model, 'unknown'), COUNT(*)
    FROM   knowledge_chunks kc
    WHERE  kc.embedding IS NOT NULL
    GROUP  BY 1
    ORDER  BY 2 DESC;
$$;
