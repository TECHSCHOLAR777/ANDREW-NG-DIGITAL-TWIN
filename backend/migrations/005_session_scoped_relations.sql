-- ============================================================
-- Migration 005: Session-Scoped Relations
-- Enforces knowledge graph scoping per chat session while
-- preserving cross-session tenant relationships.
-- ============================================================

-- 1. Add session_id column to relation_edges referencing conversation_turns (session_id)
ALTER TABLE relation_edges 
ADD COLUMN IF NOT EXISTS session_id UUID;

-- 2. Populate session_id for existing relation edges from their source conversation turns
UPDATE relation_edges re
SET session_id = ct.session_id
FROM conversation_turns ct
WHERE re.source_turn_id = ct.id 
  AND re.session_id IS NULL;

-- For any orphaned edges, generate a dummy session_id or link to first session of tenant to avoid nulls if required,
-- but we will keep it nullable for legacy/global concept connections if needed.
-- To enforce uniqueness, we drop the old constraint and add a new one including session_id.
-- Note: PostgreSQL unique constraints treat NULLs as distinct by default, so we use a COALESCE fallback or allow NULL as global.
-- We want uniqueness per session, so we add the constraint:
ALTER TABLE relation_edges
DROP CONSTRAINT IF EXISTS uq_relation_edges_spo;

ALTER TABLE relation_edges
ADD CONSTRAINT uq_relation_edges_spo
UNIQUE (tenant_id, session_id, subject_id, predicate, object_id);


-- 3. Update graph_2hop_traversal to support filtering by session_id
CREATE OR REPLACE FUNCTION graph_2hop_traversal(
    p_tenant_id   UUID,
    p_anchor_ids  UUID[],       -- vector-matched seed nodes
    p_predicates  TEXT[] DEFAULT NULL,  -- filter to specific edge types, or NULL for all
    p_max_nodes   INT  DEFAULT 50,       -- safety cap on returned nodes
    p_session_id  UUID DEFAULT NULL      -- session isolation filter (NULL = global/all sessions)
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
-- Seed: anchor nodes at hop 0
traversal(
    node_id,
    hop_distance,
    path_weight,
    predicates_path,
    visited          -- prevent cycles
) AS (
    -- Base case: anchor nodes
    SELECT
        unnest(p_anchor_ids)    AS node_id,
        0                       AS hop_distance,
        1.0::double precision   AS path_weight,
        ARRAY[]::TEXT[]         AS predicates_path,
        p_anchor_ids            AS visited

    UNION ALL

    -- Recursive case: expand one hop at a time, up to depth 2
    SELECT
        re.object_id            AS node_id,
        t.hop_distance + 1      AS hop_distance,
        -- Path weight decays multiplicatively along edges
        t.path_weight * re.weight * 0.85 AS path_weight,
        t.predicates_path || re.predicate AS predicates_path,
        t.visited || re.object_id AS visited
    FROM
        traversal t
        JOIN relation_edges re
            ON  re.tenant_id  = p_tenant_id
            AND re.subject_id = t.node_id
            AND (p_predicates IS NULL OR re.predicate = ANY(p_predicates))
            AND (p_session_id IS NULL OR re.session_id = p_session_id) -- Scoping constraint
    WHERE
        t.hop_distance < 2                    -- max 2 hops
        AND NOT (re.object_id = ANY(t.visited))  -- no cycles
        AND t.path_weight * re.weight > 0.05  -- prune very weak paths
)
-- Join traversal results with entity node details
SELECT DISTINCT ON (en.id)
    en.id               AS node_id,
    en.canonical_name,
    en.node_type,
    en.metadata,
    t.hop_distance,
    t.path_weight,
    t.predicates_path
FROM
    traversal t
    JOIN entity_nodes en
        ON en.id = t.node_id
        AND en.tenant_id = p_tenant_id
ORDER BY
    en.id,
    t.path_weight DESC   -- DISTINCT ON picks highest-weight path per node
LIMIT p_max_nodes;
$$;


-- 4. Update vector_anchored_subgraph to pass down the optional p_session_id
CREATE OR REPLACE FUNCTION vector_anchored_subgraph(
    p_tenant_id     UUID,
    p_query_embedding VECTOR(768),
    p_vector_top_k  INT   DEFAULT 5,   -- how many anchor nodes to seed with
    p_cos_threshold FLOAT DEFAULT 0.5, -- min cosine similarity for anchor
    p_predicates    TEXT[] DEFAULT NULL,
    p_session_id    UUID DEFAULT NULL   -- session isolation filter
)
RETURNS TABLE (
    node_id        UUID,
    canonical_name TEXT,
    node_type      TEXT,
    metadata       JSONB,
    hop_distance   INT,
    path_weight    FLOAT,
    vector_score   FLOAT,
    combined_score FLOAT,
    predicates_path TEXT[]
)
LANGUAGE sql STABLE
AS $$
WITH

-- Step 1: Vector ANN search to find anchor nodes
anchor_candidates AS (
    SELECT
        id,
        1 - (embedding <=> p_query_embedding) AS cos_sim   -- cosine similarity
    FROM entity_nodes
    WHERE
        tenant_id = p_tenant_id
        AND embedding IS NOT NULL
    ORDER BY embedding <=> p_query_embedding
    LIMIT p_vector_top_k * 3   -- oversample, then filter by threshold
),

anchors AS (
    SELECT id, cos_sim
    FROM anchor_candidates
    WHERE cos_sim >= p_cos_threshold
    LIMIT p_vector_top_k
),

anchor_ids AS (
    SELECT array_agg(id) AS ids FROM anchors
),

-- Step 2: 2-hop graph traversal from anchors with session filter
subgraph AS (
    SELECT g.*
    FROM
        anchor_ids ai,
        LATERAL graph_2hop_traversal(
            p_tenant_id,
            ai.ids,
            p_predicates,
            50,
            p_session_id
        ) g
    WHERE ai.ids IS NOT NULL
)

-- Step 3: Merge graph results with vector scores
SELECT
    sg.node_id,
    sg.canonical_name,
    sg.node_type,
    sg.metadata,
    sg.hop_distance,
    sg.path_weight,
    coalesce(a.cos_sim, 0.0)   AS vector_score,
    -- Combined score: anchor nodes get full vector score, neighbors get graph weight
    CASE sg.hop_distance
        WHEN 0 THEN a.cos_sim
        ELSE sg.path_weight * (1 - sg.hop_distance * 0.15)
    END                         AS combined_score,
    sg.predicates_path
FROM
    subgraph sg
    LEFT JOIN anchors a ON a.id = sg.node_id
ORDER BY combined_score DESC;
$$;
