"""
All SQL used by the event router.

Kept in one place so the locking semantics are reviewable independently
from the Python logic.
"""


# ─────────────────────────────────────────────
# Claim
# Atomically pick up the next batch of unrouted events, ordered by
# severity then arrival time. SKIP LOCKED lets multiple router
# instances coexist safely; LIMIT keeps each transaction short.
# ─────────────────────────────────────────────

CLAIM_BATCH = """
  SELECT
    id,
    robot_id,
    event_type,
    severity,
    source_component,
    payload
  FROM robot_events
  WHERE status IN ('pending', 'dispatched')
    AND workflow_id IS NULL
  ORDER BY
    CASE severity
      WHEN 'emergency' THEN 0
      WHEN 'critical'  THEN 1
      WHEN 'warning'   THEN 2
      WHEN 'info'      THEN 3
      ELSE              4
    END,
    created_at ASC,
    id ASC
  FOR UPDATE SKIP LOCKED
  LIMIT $1
"""


# Move an event from pending/dispatched into in_progress as part of the
# claim transaction. From this point on, the status itself is the soft
# lock — no other router can re-claim it.
MARK_IN_PROGRESS_NO_WORKFLOW = """
  UPDATE robot_events
  SET status          = 'in_progress',
      last_updated_at = NOW()
  WHERE id = $1
    AND status IN ('pending', 'dispatched')
"""


# Bind a workflow_id to a claimed event. Done *after* the claim
# transaction commits so the launcher decides the workflow_id.
LINK_WORKFLOW = """
  UPDATE robot_events
  SET workflow_id     = $1::uuid,
      last_updated_at = NOW()
  WHERE id = $2
"""


# Terminal transitions (driven by the tracker once the workflow ends).
COMPLETE_EVENT = """
  UPDATE robot_events
  SET status          = 'completed',
      completed_at    = NOW(),
      processed       = TRUE,
      last_updated_at = NOW()
  WHERE id = $1
    AND status = 'in_progress'
"""

FAIL_EVENT = """
  UPDATE robot_events
  SET status          = 'failed',
      completed_at    = NOW(),
      processed       = TRUE,
      last_updated_at = NOW()
  WHERE id = $1
    AND status = 'in_progress'
"""


# ─────────────────────────────────────────────
# Input builder
# ─────────────────────────────────────────────

SELECT_ROBOT_STATE = """
  SELECT
    robot_id, robot_name,
    x, y, theta,
    current_zone,
    battery_pct,
    operational_status,
    navigation_status,
    current_mission_id,
    current_task_id,
    last_heartbeat,
    health_score,
    metadata,
    updated_at
  FROM robot_state
  WHERE robot_id = $1
"""


# Most-recent active mission for the robot.
SELECT_ACTIVE_MISSION = """
  SELECT
    mission_id,
    mission_type,
    priority,
    status,
    source_location,
    destination_location,
    assigned_agent,
    deadline,
    started_at
  FROM missions
  WHERE robot_id = $1
    AND status IN ('active', 'in_progress', 'running')
  ORDER BY priority DESC, started_at DESC NULLS LAST
  LIMIT 1
"""


# ─────────────────────────────────────────────
# Workflow execution
# ─────────────────────────────────────────────

INSERT_WORKFLOW_EXECUTION = """
  INSERT INTO workflow_execution (
    workflow_id,
    workflow_type,
    status,
    current_node,
    started_at,
    updated_at
  )
  VALUES (
    $1::uuid,
    $2,
    'running',
    NULL,
    NOW(),
    NOW()
  )
"""


# Tracker reconciliation: find workflows that finished but whose linked
# event is still in_progress. Used to converge state if LangGraph
# completes without a direct callback path back to the router.
SELECT_FINISHED_WORKFLOWS_WITH_OPEN_EVENTS = """
  SELECT
    we.workflow_id,
    we.status                                AS workflow_status,
    re.id                                    AS event_id
  FROM workflow_execution we
  JOIN robot_events re
    ON re.workflow_id = we.workflow_id
  WHERE we.status IN ('completed', 'failed')
    AND re.status  = 'in_progress'
"""
