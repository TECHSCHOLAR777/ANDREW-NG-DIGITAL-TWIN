-- 015_general_context_memory.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Broaden contextual memory from a student-only model to a general digital-twin
-- model that also serves researchers, engineers, founders, product/business
-- leaders, and the public.
--
-- WHAT CHANGES
--   entity_nodes.node_type carried an inline CHECK restricting it to
--   ('Student','Concept','Project','Tool','Paper'). That is the ONLY schema
--   object that rejects the broader professional context the design system
--   requires. Predicates are free TEXT and validated in application code, so
--   no schema change is needed for the new predicates
--   (works_at, leads, researches, building, interested_in, prefers, decided,
--    concerned_about, discussed, collaborates_on).
--
-- BACKWARD COMPATIBILITY
--   The new CHECK is a strict SUPERSET of the old one. Every existing row stays
--   valid; nothing is rewritten or deleted. "Student" is retained as the
--   internal self-node type so all Student-anchored logic (graph BFS roots,
--   resolve_student_name via 'named'/'is' edges, curriculum learner state)
--   keeps working unchanged. The UI maps Student to a neutral "Person"/"You"
--   label at display time — a presentation concern, not a data migration.
--
--   The inline column CHECK from migration 001 is auto-named
--   entity_nodes_node_type_check by Postgres. DROP ... IF EXISTS makes this
--   idempotent and safe even if the constraint was named differently.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE entity_nodes
    DROP CONSTRAINT IF EXISTS entity_nodes_node_type_check;

ALTER TABLE entity_nodes
    ADD CONSTRAINT entity_nodes_node_type_check
    CHECK (node_type IN (
        -- Original, education-oriented types (preserved)
        'Student', 'Concept', 'Project', 'Tool', 'Paper',
        -- General professional / research context
        'Person', 'Organization', 'Industry', 'Goal', 'Preference', 'ResearchArea'
    ));

COMMENT ON COLUMN entity_nodes.node_type IS
    'Closed-world node category. Student is the internal self-node type (shown '
    'to users as Person/You). Educational types remain a valid subset of the '
    'general context model.';
