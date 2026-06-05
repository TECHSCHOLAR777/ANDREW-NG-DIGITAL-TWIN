-- ============================================================
-- Migration 002: Entity Resolution + 2-Hop Graph Traversal
-- Andrew Ng Digital Twin
-- ============================================================

-- ============================================================
-- FUNCTION: resolve_entity
-- Maps a raw surface form (e.g. "NNs") to a canonical entity_node_id.
-- Resolution priority:
--   1. Exact alias match
--   2. Trigram fuzzy alias match (similarity > 0.6)
--   3. Exact canonical_name match (case-insensitive)
--   4. Returns NULL if no match found
-- ============================================================
CREATE OR REPLACE FUNCTION resolve_entity(
    p_tenant_id   UUID,
    p_surface     TEXT,          -- raw text from conversation ("NNs")
    p_threshold   FLOAT DEFAULT 0.6  -- trigram similarity cutoff
)
RETURNS UUID
LANGUAGE plpgsql STABLE
AS $$
DECLARE
    v_node_id UUID;
    v_norm    TEXT;
BEGIN
    -- Normalize: lowercase, strip punctuation, unaccent
    v_norm := lower(unaccent(trim(p_surface)));

    -- Priority 1: Exact alias match
    SELECT entity_node_id INTO v_node_id
    FROM   entity_aliases
    WHERE  tenant_id = p_tenant_id
      AND  alias = v_norm
    LIMIT 1;

    IF v_node_id IS NOT NULL THEN RETURN v_node_id; END IF;

    -- Priority 2: Fuzzy trigram alias match
    SELECT entity_node_id INTO v_node_id
    FROM   entity_aliases
    WHERE  tenant_id = p_tenant_id
      AND  similarity(alias, v_norm) >= p_threshold
    ORDER  BY similarity(alias, v_norm) DESC
    LIMIT  1;

    IF v_node_id IS NOT NULL THEN RETURN v_node_id; END IF;

    -- Priority 3: Direct canonical_name match
    SELECT id INTO v_node_id
    FROM   entity_nodes
    WHERE  tenant_id = p_tenant_id
      AND  lower(canonical_name) = v_norm
    LIMIT  1;

    RETURN v_node_id;  -- NULL if still not found
END;
$$;


-- ============================================================
-- FUNCTION: upsert_entity
-- Finds or creates an entity node, and registers the alias.
-- Called from Python during triplet extraction.
-- ============================================================
CREATE OR REPLACE FUNCTION upsert_entity(
    p_tenant_id     UUID,
    p_canonical     TEXT,        -- e.g. "Neural Networks"
    p_node_type     TEXT,        -- e.g. "Concept"
    p_alias         TEXT,        -- e.g. "NNs" (the raw surface form)
    p_metadata      JSONB DEFAULT '{}'
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_node_id UUID;
BEGIN
    -- Upsert the canonical entity node
    INSERT INTO entity_nodes (tenant_id, canonical_name, node_type, metadata)
    VALUES (p_tenant_id, p_canonical, p_node_type, p_metadata)
    ON CONFLICT (tenant_id, canonical_name)
    DO UPDATE SET
        metadata   = entity_nodes.metadata || p_metadata,  -- merge metadata
        updated_at = NOW()
    RETURNING id INTO v_node_id;

    -- Register the alias (lowercase normalized)
    INSERT INTO entity_aliases (tenant_id, alias, entity_node_id, source)
    VALUES (p_tenant_id, lower(unaccent(trim(p_alias))), v_node_id, 'llm')
    ON CONFLICT (tenant_id, alias) DO NOTHING;

    -- Also register the canonical name itself as an alias
    INSERT INTO entity_aliases (tenant_id, alias, entity_node_id, source)
    VALUES (p_tenant_id, lower(unaccent(trim(p_canonical))), v_node_id, 'manual')
    ON CONFLICT (tenant_id, alias) DO NOTHING;

    RETURN v_node_id;
END;
$$;


-- ============================================================
-- FUNCTION: graph_2hop_traversal
-- Fast (<10ms) 2-hop traversal from a set of anchor node IDs.
--
-- Algorithm:
--   1. Start from anchor_ids (vector-matched nodes from the query).
--   2. Hop 1: find all direct neighbors via relation_edges.
--   3. Hop 2: find all neighbors of neighbors.
--   4. Return ranked subgraph rows with accumulated path weight.
--
-- The recursive CTE is capped at depth=2 to guarantee bounded time.
-- A bloom-filter-like visited array prevents cycles.
-- ============================================================
CREATE OR REPLACE FUNCTION graph_2hop_traversal(
    p_tenant_id   UUID,
    p_anchor_ids  UUID[],       -- vector-matched seed nodes
    p_predicates  TEXT[] DEFAULT NULL,  -- filter to specific edge types, or NULL for all
    p_max_nodes   INT  DEFAULT 50       -- safety cap on returned nodes
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
        1.0                     AS path_weight,
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


-- ============================================================
-- FUNCTION: vector_anchored_subgraph
-- Full pipeline: embed query → find anchor nodes → 2-hop traversal.
-- Call this from Python by passing the pre-computed query embedding.
--
-- Returns graph nodes ordered by combined vector + graph relevance.
-- ============================================================
CREATE OR REPLACE FUNCTION vector_anchored_subgraph(
    p_tenant_id     UUID,
    p_query_embedding VECTOR(768),
    p_vector_top_k  INT   DEFAULT 5,   -- how many anchor nodes to seed with
    p_cos_threshold FLOAT DEFAULT 0.5, -- min cosine similarity for anchor
    p_predicates    TEXT[] DEFAULT NULL
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

-- Step 2: 2-hop graph traversal from anchors
subgraph AS (
    SELECT g.*
    FROM
        anchor_ids ai,
        LATERAL graph_2hop_traversal(
            p_tenant_id,
            ai.ids,
            p_predicates
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
