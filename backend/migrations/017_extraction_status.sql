-- ============================================================
-- Migration 017: Extraction status tracks extractable turns
--
-- Triplet extraction mines the user's message and treats the assistant reply
-- only as context. Assistant rows were nevertheless left with the column's
-- FALSE default, so every completed conversation appeared permanently pending
-- and the retry index accumulated rows the sweeper would never process.
-- ============================================================

UPDATE conversation_turns
SET    triplets_extracted = TRUE
WHERE  role = 'assistant'
  AND  triplets_extracted = FALSE;

DROP INDEX IF EXISTS idx_turns_unprocessed;

CREATE INDEX idx_turns_unprocessed
ON conversation_turns (tenant_id, created_at)
WHERE triplets_extracted = FALSE
  AND role = 'user';
