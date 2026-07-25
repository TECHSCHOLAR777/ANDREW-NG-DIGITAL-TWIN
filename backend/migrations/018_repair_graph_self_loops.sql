-- ============================================================
-- Migration 018: Repair malformed self-referencing graph edges
--
-- Gemini can occasionally place the object in both endpoint fields. For
-- predicates that describe the user, the intended subject is the tenant's
-- canonical Student node. Repair those rows, retire ambiguous self-loops, and
-- prevent another live self-loop from entering the graph.
-- ============================================================

-- If the correct edge already exists, retain it and retire the malformed copy
-- before attempting the repair. This avoids the live-edge uniqueness index.
UPDATE relation_edges AS broken
SET    invalidated_at = NOW(),
       invalidated_reason = 'Malformed self-reference duplicated an existing user relationship',
       updated_at = NOW()
FROM   entity_nodes AS student
WHERE  broken.invalidated_at IS NULL
  AND  broken.subject_id = broken.object_id
  AND  broken.predicate IN (
      'struggles_with', 'mastered', 'curious_about', 'works_in', 'studied',
      'applied', 'confused_about', 'wants_to_learn', 'named', 'is',
      'works_at', 'leads', 'researches', 'building', 'interested_in',
      'prefers', 'decided', 'concerned_about', 'discussed', 'collaborates_on'
  )
  AND  student.tenant_id = broken.tenant_id
  AND  student.node_type = 'Student'
  AND  lower(student.canonical_name) = 'student'
  AND  student.id <> broken.object_id
  AND  EXISTS (
      SELECT 1
      FROM relation_edges AS existing
      WHERE existing.tenant_id = broken.tenant_id
        AND existing.session_id IS NOT DISTINCT FROM broken.session_id
        AND existing.subject_id = student.id
        AND existing.predicate = broken.predicate
        AND existing.object_id = broken.object_id
        AND existing.invalidated_at IS NULL
  );

-- The predicate contract makes these relationships unambiguous: their subject
-- is always the signed-in user's canonical Student node.
UPDATE relation_edges AS broken
SET    subject_id = student.id,
       updated_at = NOW()
FROM   entity_nodes AS student
WHERE  broken.invalidated_at IS NULL
  AND  broken.subject_id = broken.object_id
  AND  broken.predicate IN (
      'struggles_with', 'mastered', 'curious_about', 'works_in', 'studied',
      'applied', 'confused_about', 'wants_to_learn', 'named', 'is',
      'works_at', 'leads', 'researches', 'building', 'interested_in',
      'prefers', 'decided', 'concerned_about', 'discussed', 'collaborates_on'
  )
  AND  student.tenant_id = broken.tenant_id
  AND  student.node_type = 'Student'
  AND  lower(student.canonical_name) = 'student'
  AND  student.id <> broken.object_id;

-- A self-loop outside the user-anchored predicate contract has no safe inferred
-- endpoint. Preserve it as invalidated history instead of inventing a fact.
UPDATE relation_edges
SET    invalidated_at = NOW(),
       invalidated_reason = 'Malformed self-referencing relationship',
       updated_at = NOW()
WHERE  invalidated_at IS NULL
  AND  subject_id = object_id;

ALTER TABLE relation_edges
    DROP CONSTRAINT IF EXISTS relation_edges_no_live_self_loop;

ALTER TABLE relation_edges
    ADD CONSTRAINT relation_edges_no_live_self_loop
    CHECK (subject_id <> object_id OR invalidated_at IS NOT NULL);
