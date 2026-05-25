"""
SQL for the event system.

Kept in one place so query shape is reviewable independently from the
repository's Python logic. Parameter order matches repository call sites.
"""

# Insert a brand-new event row. Returns the generated id.
INSERT_EVENT = """
  INSERT INTO robot_events (
    robot_id,
    event_type,
    severity,
    source_component,
    payload,
    dedup_key,
    dedup_count,
    status,
    processed,
    created_at,
    last_updated_at
  )
  VALUES (
    $1, $2, $3, $4, $5::jsonb,
    $6, 1,
    'pending', FALSE,
    $7, $7
  )
  RETURNING id
"""


# Dedup: find the most recent row with the same fingerprint.
# Returns the row whether open or terminal — the deduper decides what
# to do based on status + last_updated_at.
FIND_LATEST_BY_DEDUP_KEY = """
  SELECT id, status, last_updated_at, dedup_count
  FROM robot_events
  WHERE dedup_key = $1
  ORDER BY id DESC
  LIMIT 1
"""


# Dedup absorb: increment count + touch timestamp on the existing row.
BUMP_DEDUP = """
  UPDATE robot_events
  SET dedup_count     = dedup_count + 1,
      last_updated_at = NOW()
  WHERE id = $1
"""


# Lifecycle transitions

MARK_DISPATCHED = """
  UPDATE robot_events
  SET status          = 'dispatched',
      dispatched_at   = COALESCE(dispatched_at, NOW()),
      last_updated_at = NOW()
  WHERE id = $1
    AND status = 'pending'
"""


MARK_IN_PROGRESS = """
  UPDATE robot_events
  SET status          = 'in_progress',
      workflow_id     = $2::uuid,
      last_updated_at = NOW()
  WHERE id = $1
    AND status = 'dispatched'
"""


MARK_COMPLETED = """
  UPDATE robot_events
  SET status          = 'completed',
      completed_at    = NOW(),
      processed       = TRUE,
      last_updated_at = NOW()
  WHERE id = $1
    AND status = 'in_progress'
"""


MARK_FAILED = """
  UPDATE robot_events
  SET status          = 'failed',
      completed_at    = NOW(),
      processed       = TRUE,
      last_updated_at = NOW()
  WHERE id = $1
    AND status IN ('dispatched', 'in_progress')
"""


# Time-out sweeper: anything still pending past the cutoff is expired.
EXPIRE_STALE_PENDING = """
  UPDATE robot_events
  SET status          = 'expired',
      processed       = TRUE,
      completed_at    = NOW(),
      last_updated_at = NOW()
  WHERE status = 'pending'
    AND created_at < NOW() - ($1::text || ' seconds')::interval
  RETURNING id
"""


# Cross-process orchestrator wakeup. The payload is just the event id;
# the orchestrator looks the row up.
NOTIFY_NEW_EVENT = "SELECT pg_notify('robot_events_new', $1)"
