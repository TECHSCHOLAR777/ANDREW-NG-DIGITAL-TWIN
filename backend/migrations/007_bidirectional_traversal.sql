-- ============================================================
-- Migration 007: Bidirectional Graph Traversal
--
-- Bug fixed: graph_2hop_traversal only followed edges in the
-- subject -> object direction. Ten of the thirteen predicates
-- have Student as subject (Student -[struggles_with]-> Concept,
-- etc.), so the graph is nearly a star pointing outward from the
-- Student node. Starting from a Concept anchor (which is what
-- vector search finds), there were almost never outgoing edges
-- to follow — the "2-hop traversal" terminated at hop 0.
--
-- Fix: expand over the UNDIRECTED graph. From node N, follow any
-- edge touching N and step to the opposite endpoint. Edge
-- direction still matters semantically (it is preserved in
-- predicates_path and in relation_edges itself) — it just no
-- longer restricts neighbourhood discovery.
--
-- Signature is identical to migration 005, so the caller
-- vector_anchored_subgraph needs no change.
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
traversal(
    node_id,
    hop_distance,
    path_weight,
    predicates_path,
    visited
) AS (
    -- Base case: anchor nodes
    SELECT
        unnest(p_anchor_ids)    AS node_id,
        0                       AS hop_distance,
        1.0::double precision   AS path_weight,
        ARRAY[]::TEXT[]         AS predicates_path,
        p_anchor_ids            AS visited

    UNION ALL

    -- Recursive case: expand one hop over the UNDIRECTED graph.
    -- The next node is whichever endpoint of the edge we did not
    -- arrive from.
    SELECT
        CASE WHEN re.subject_id = t.node_id
             THEN re.object_id
             ELSE re.subject_id
        END                     AS node_id,
        t.hop_distance + 1      AS hop_distance,
        t.path_weight * re.weight * 0.85 AS path_weight,
        t.predicates_path || re.predicate AS predicates_path,
        t.visited || (CASE WHEN re.subject_id = t.node_id
                           THEN re.object_id
                           ELSE re.subject_id
                      END)      AS visited
    FROM
        traversal t
        JOIN relation_edges re
            ON  re.tenant_id = p_tenant_id
            AND (re.subject_id = t.node_id OR re.object_id = t.node_id)
            AND (p_predicates IS NULL OR re.predicate = ANY(p_predicates))
            AND (p_session_id IS NULL OR re.session_id = p_session_id)
    WHERE
        t.hop_distance < 2
        AND NOT ((CASE WHEN re.subject_id = t.node_id
                       THEN re.object_id
                       ELSE re.subject_id
                  END) = ANY(t.visited))
        AND t.path_weight * re.weight > 0.05
)
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
    t.path_weight DESC
LIMIT p_max_nodes;
$$;
