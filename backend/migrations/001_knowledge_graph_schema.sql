-- ============================================================
-- Migration 001: Knowledge Graph Schema
-- Andrew Ng Digital Twin — Multi-Tenant Production DB
-- ============================================================
-- Prerequisites: supabase/postgres with pgvector extension
-- Run: psql $DATABASE_URL -f 001_knowledge_graph_schema.sql
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- for fuzzy entity resolution
CREATE EXTENSION IF NOT EXISTS unaccent;  -- for normalizing accented chars

-- ============================================================
-- TENANTS (multi-tenant root)
-- ============================================================
CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- ENTITY NODES
-- Represents any learnable concept, person, or project.
-- The `canonical_name` column is the resolved, deduplicated name.
-- Aliases are stored separately in entity_aliases for resolution.
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Canonical resolved name (e.g. "Neural Networks", not "NNs")
    canonical_name  TEXT NOT NULL,

    -- node type: 'Student' | 'Concept' | 'Project' | 'Tool' | 'Paper'
    node_type       TEXT NOT NULL CHECK (node_type IN ('Student','Concept','Project','Tool','Paper')),

    -- Rich metadata stored as JSONB for flexibility
    metadata        JSONB NOT NULL DEFAULT '{}',

    -- Vector embedding of the canonical_name + metadata summary
    -- Using text-embedding-004 (768 dimensions)
    embedding       VECTOR(768),

    -- Full-text search document (auto-populated by trigger below)
    fts_document    TSVECTOR,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A canonical name must be unique within a tenant
    UNIQUE (tenant_id, canonical_name)
);

-- ============================================================
-- ENTITY ALIASES (Entity Resolution table)
-- Maps raw surface forms → canonical entity_node ids.
-- e.g. "NNs" → "Neural Networks", "backprop" → "Backpropagation"
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_aliases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    alias           TEXT NOT NULL,                             -- raw surface form (lowercased)
    entity_node_id  UUID NOT NULL REFERENCES entity_nodes(id) ON DELETE CASCADE,
    confidence      FLOAT NOT NULL DEFAULT 1.0,               -- 0-1 confidence score
    source          TEXT NOT NULL DEFAULT 'manual',           -- 'manual' | 'llm' | 'fuzzy'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (tenant_id, alias)
);

-- ============================================================
-- RELATION EDGES
-- Directed hyperedges between entity nodes.
-- e.g. (student_A) -[struggles_with]-> (Neural Networks)
-- ============================================================
CREATE TABLE IF NOT EXISTS relation_edges (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Subject → Predicate → Object (SPO triple)
    subject_id      UUID NOT NULL REFERENCES entity_nodes(id) ON DELETE CASCADE,
    predicate       TEXT NOT NULL,   -- e.g. 'struggles_with', 'works_in', 'mastered', 'curious_about'
    object_id       UUID NOT NULL REFERENCES entity_nodes(id) ON DELETE CASCADE,

    -- Scalar weight for ranking (1.0 = strong, decays over time)
    weight          FLOAT NOT NULL DEFAULT 1.0,

    -- Provenance: which conversation turn created this edge
    source_turn_id  UUID,

    -- Evidence text from the conversation (for audit/explainability)
    evidence        TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- KNOWLEDGE CHUNKS (RAG document store)
-- Replaces Chroma + BM25 with pgvector + FTS in one table.
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Source document metadata
    source_file     TEXT NOT NULL,
    source_type     TEXT NOT NULL DEFAULT 'lecture',  -- 'lecture' | 'paper' | 'newsletter' | 'qa'
    chunk_index     INT  NOT NULL,
    chunk_text      TEXT NOT NULL,

    -- Authority prior: lecture=1.0, paper=0.8, newsletter=0.5, qa=0.3
    -- Used in RRF fusion to boost high-quality sources
    authority_prior FLOAT NOT NULL DEFAULT 1.0,

    -- pgvector embedding (text-embedding-004)
    embedding       VECTOR(768),

    -- Native PostgreSQL full-text search
    fts_document    TSVECTOR,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- CONVERSATION TURNS (session memory)
-- ============================================================
CREATE TABLE IF NOT EXISTS conversation_turns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id      UUID NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content         TEXT NOT NULL,
    turn_index      INT  NOT NULL,

    -- Triplets extracted from this turn (after async processing)
    triplets_extracted BOOLEAN NOT NULL DEFAULT FALSE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================

-- Vector ANN index (IVFFlat) on entity nodes
-- lists=100 is appropriate for up to ~1M vectors; tune as needed
CREATE INDEX IF NOT EXISTS idx_entity_nodes_embedding
    ON entity_nodes USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Vector ANN index on knowledge chunks
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- GIN index for FTS on knowledge chunks
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_fts
    ON knowledge_chunks USING GIN (fts_document);

-- GIN index for FTS on entity nodes
CREATE INDEX IF NOT EXISTS idx_entity_nodes_fts
    ON entity_nodes USING GIN (fts_document);

-- Trigram index on entity_aliases for fuzzy entity resolution
CREATE INDEX IF NOT EXISTS idx_entity_aliases_trgm
    ON entity_aliases USING GIN (alias gin_trgm_ops);

-- Relation edge indexes for fast traversal
CREATE INDEX IF NOT EXISTS idx_relation_edges_subject
    ON relation_edges (tenant_id, subject_id, predicate);
CREATE INDEX IF NOT EXISTS idx_relation_edges_object
    ON relation_edges (tenant_id, object_id, predicate);

-- Conversation turn index
CREATE INDEX IF NOT EXISTS idx_conversation_turns_session
    ON conversation_turns (tenant_id, session_id, turn_index);

-- ============================================================
-- TRIGGERS: Auto-update FTS documents
-- ============================================================

-- Trigger function for knowledge_chunks FTS
CREATE OR REPLACE FUNCTION update_chunk_fts()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.fts_document :=
        setweight(to_tsvector('english', coalesce(NEW.source_file, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.chunk_text,  '')), 'B');
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_chunk_fts
BEFORE INSERT OR UPDATE ON knowledge_chunks
FOR EACH ROW EXECUTE FUNCTION update_chunk_fts();

-- Trigger function for entity_nodes FTS
CREATE OR REPLACE FUNCTION update_entity_fts()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.fts_document :=
        setweight(to_tsvector('english', coalesce(NEW.canonical_name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.metadata::text,  '')), 'C');
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_entity_fts
BEFORE INSERT OR UPDATE ON entity_nodes
FOR EACH ROW EXECUTE FUNCTION update_entity_fts();

-- Trigger: auto-update updated_at
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$;

CREATE TRIGGER trg_entity_nodes_updated_at
BEFORE UPDATE ON entity_nodes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_relation_edges_updated_at
BEFORE UPDATE ON relation_edges
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
