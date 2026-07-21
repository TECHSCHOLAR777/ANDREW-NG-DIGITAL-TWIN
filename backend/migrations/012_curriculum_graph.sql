-- ============================================================
-- Migration 012: Curriculum Graph
--
-- THE PROBLEM THIS SOLVES
-- Every node in the knowledge graph so far comes from conversation.
-- That means the graph only knows concepts the student has already
-- mentioned, which is exactly the set of things they do not need
-- help discovering. It can say "you struggle with backpropagation".
-- It cannot say "you struggle with backpropagation because you never
-- got the chain rule", because it has no idea one depends on the
-- other.
--
-- This adds the missing layer: a prerequisite DAG over machine
-- learning concepts, extracted once from the corpus rather than from
-- any conversation. The student graph then becomes an OVERLAY on it.
-- The curriculum says what depends on what; the student layer says
-- where this person is.
--
-- WHY NAME-KEYED, TENANT-FREE TABLES
-- The obvious move is to store these as relation_edges with a
-- sentinel session, which migration 009 made possible. It is the
-- wrong move. entity_nodes is UNIQUE(tenant_id, canonical_name), so
-- curriculum concepts would need either a shared tenant (and then
-- foreign keys pointing across tenant boundaries, which RLS in
-- migration 011 would have to special-case) or duplication into every
-- tenant (and then the "shared" structure is not shared at all).
--
-- Curriculum structure is genuinely global and has no owner. Keying
-- it by normalised concept name gives a clean join to any tenant's
-- entity_nodes on lower(canonical_name), with no cross-tenant
-- references and nothing for RLS to reason about.
-- ============================================================

CREATE TABLE IF NOT EXISTS curriculum_concepts (
    -- Normalised key: lowercased, punctuation stripped. Joins to
    -- entity_nodes.canonical_name after the same normalisation.
    name          TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,

    -- Difficulty tier, used by pedagogical retrieval to choose which
    -- explanation of a concept to surface for a given learner.
    difficulty    TEXT NOT NULL DEFAULT 'applied'
                  CHECK (difficulty IN ('intuitive', 'applied', 'formal')),

    -- One line, for path display and gap explanations.
    summary       TEXT,

    -- Where in the corpus this concept is taught, so a learning path
    -- can point at reading rather than just naming a gap.
    source_files  TEXT[] NOT NULL DEFAULT '{}',

    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS curriculum_edges (
    -- Read as: `prerequisite` must be understood before `concept`.
    prerequisite  TEXT NOT NULL REFERENCES curriculum_concepts(name) ON DELETE CASCADE,
    concept       TEXT NOT NULL REFERENCES curriculum_concepts(name) ON DELETE CASCADE,

    -- Extraction confidence. Weak edges are still stored so the
    -- threshold is a query-time decision rather than a lossy one.
    confidence    FLOAT NOT NULL DEFAULT 0.8,
    evidence      TEXT,

    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (prerequisite, concept),
    -- A concept cannot require itself. Cycles of length > 1 are
    -- rejected by the loader, which a CHECK cannot express.
    CONSTRAINT no_self_prerequisite CHECK (prerequisite <> concept)
);

CREATE INDEX IF NOT EXISTS idx_curriculum_edges_concept
    ON curriculum_edges (concept);
CREATE INDEX IF NOT EXISTS idx_curriculum_edges_prereq
    ON curriculum_edges (prerequisite);


-- ============================================================
-- FUNCTION: normalise_concept
-- One definition of the join key, so Python and SQL cannot disagree
-- about whether "Neural Networks" and "neural-networks" are the same
-- concept.
-- ============================================================
CREATE OR REPLACE FUNCTION normalise_concept(p_name TEXT)
RETURNS TEXT
LANGUAGE sql IMMUTABLE
AS $$
    SELECT regexp_replace(lower(trim(coalesce(p_name, ''))), '[^a-z0-9]+', ' ', 'g');
$$;


-- ============================================================
-- FUNCTION: concept_prerequisites
-- All prerequisites of a concept, transitively, with depth.
--
-- Depth matters for ordering a learning path: something four steps
-- upstream should be studied before something one step upstream.
-- ============================================================
CREATE OR REPLACE FUNCTION concept_prerequisites(
    p_concept    TEXT,
    p_max_depth  INT DEFAULT 6,
    p_min_conf   FLOAT DEFAULT 0.5
)
RETURNS TABLE (
    name         TEXT,
    display_name TEXT,
    difficulty   TEXT,
    summary      TEXT,
    depth        INT
)
LANGUAGE sql STABLE
AS $$
WITH RECURSIVE walk(name, depth, visited) AS (
    SELECT normalise_concept(p_concept), 0, ARRAY[normalise_concept(p_concept)]

    UNION ALL

    SELECT ce.prerequisite,
           w.depth + 1,
           w.visited || ce.prerequisite
    FROM   walk w
    JOIN   curriculum_edges ce ON ce.concept = w.name
    WHERE  w.depth < p_max_depth
      AND  ce.confidence >= p_min_conf
      -- Guards against cycles the loader failed to reject.
      AND  NOT (ce.prerequisite = ANY(w.visited))
)
SELECT DISTINCT ON (c.name)
       c.name, c.display_name, c.difficulty, c.summary, w.depth
FROM   walk w
JOIN   curriculum_concepts c ON c.name = w.name
WHERE  w.depth > 0            -- exclude the target itself
ORDER  BY c.name, w.depth DESC;   -- deepest occurrence wins the ordering
$$;


-- ============================================================
-- VIEW: curriculum_roots
-- Concepts with no prerequisites. Useful as entry points for a
-- learner with an empty graph, and as a sanity check after a build:
-- a DAG where everything has a prerequisite has a cycle.
-- ============================================================
CREATE OR REPLACE VIEW curriculum_roots AS
SELECT c.*
FROM   curriculum_concepts c
LEFT   JOIN curriculum_edges ce ON ce.concept = c.name
WHERE  ce.concept IS NULL;
