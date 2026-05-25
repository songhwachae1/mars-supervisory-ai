-- =====================================================
-- Migration 0001 — robot_events lifecycle + dedup
-- Adds status, dedup_key, dedup_count, workflow_id,
-- dispatched_at, completed_at, last_updated_at to
-- robot_events. Safe to re-run.
-- =====================================================

ALTER TABLE robot_events
  ADD COLUMN IF NOT EXISTS status          VARCHAR(30) DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS dedup_key       VARCHAR(150),
  ADD COLUMN IF NOT EXISTS dedup_count     INT DEFAULT 1,
  ADD COLUMN IF NOT EXISTS workflow_id     UUID,
  ADD COLUMN IF NOT EXISTS dispatched_at   TIMESTAMP,
  ADD COLUMN IF NOT EXISTS completed_at    TIMESTAMP,
  ADD COLUMN IF NOT EXISTS last_updated_at TIMESTAMP DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_robot_events_status
ON robot_events(status);

CREATE INDEX IF NOT EXISTS idx_robot_events_dedup_open
ON robot_events(dedup_key, status);

-- Backfill status from legacy processed flag
UPDATE robot_events
SET status = CASE
  WHEN processed THEN 'completed'
  ELSE 'pending'
END
WHERE status IS NULL;
