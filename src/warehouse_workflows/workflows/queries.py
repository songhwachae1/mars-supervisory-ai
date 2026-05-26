"""
SQL used by workflow nodes + lifecycle helpers.

Grouped by table to keep diffs reviewable when the schema evolves.
"""


# ─────────────────────────────────────────────
# workflow_execution
# ─────────────────────────────────────────────

MARK_WORKFLOW_COMPLETED = """
  UPDATE workflow_execution
  SET status        = 'completed',
      current_node  = $2,
      updated_at    = NOW()
  WHERE workflow_id = $1::uuid
"""

MARK_WORKFLOW_FAILED = """
  UPDATE workflow_execution
  SET status        = 'failed',
      current_node  = $2,
      updated_at    = NOW()
  WHERE workflow_id = $1::uuid
"""

UPDATE_WORKFLOW_CURRENT_NODE = """
  UPDATE workflow_execution
  SET current_node = $2,
      updated_at   = NOW()
  WHERE workflow_id = $1::uuid
"""


# ─────────────────────────────────────────────
# workflow_checkpoints (audit log; separate from LangGraph's
# internal checkpointer tables — this is for humans)
# ─────────────────────────────────────────────

INSERT_AUDIT_CHECKPOINT = """
  INSERT INTO workflow_checkpoints (
    workflow_id, graph_node, checkpoint_state
  )
  VALUES ($1::uuid, $2, $3::jsonb)
"""


# ─────────────────────────────────────────────
# agent_commands
# ─────────────────────────────────────────────

INSERT_AGENT_COMMAND = """
  INSERT INTO agent_commands (
    command_id, mission_id, robot_id,
    source_agent, command_type, payload, priority,
    status, created_at
  )
  VALUES (
    gen_random_uuid(), $1::uuid, $2,
    $3, $4, $5::jsonb, $6,
    'pending', NOW()
  )
  RETURNING command_id
"""


# ─────────────────────────────────────────────
# missions
# ─────────────────────────────────────────────

UPDATE_MISSION_STATUS = """
  UPDATE missions
  SET status = $2
  WHERE mission_id = $1::uuid
"""

COMPLETE_MISSION = """
  UPDATE missions
  SET status        = 'completed',
      completed_at  = NOW()
  WHERE mission_id = $1::uuid
"""

FIND_PENDING_UNASSIGNED_MISSION = """
  SELECT
    mission_id, mission_type, priority, scheduling_priority,
    source_location, destination_location, deadline
  FROM missions
  WHERE status IN ('pending', 'queued')
    AND (robot_id IS NULL OR robot_id = '')
  ORDER BY
    COALESCE(scheduling_priority, priority) DESC,
    COALESCE(deadline, 'infinity'::timestamp) ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED
"""

ASSIGN_MISSION_TO_ROBOT = """
  UPDATE missions
  SET robot_id   = $2,
      status     = 'active',
      started_at = COALESCE(started_at, NOW())
  WHERE mission_id = $1::uuid
"""


# ─────────────────────────────────────────────
# tasks
# ─────────────────────────────────────────────

COMPLETE_TASK = """
  UPDATE tasks
  SET status       = 'completed',
      completed_at = NOW()
  WHERE task_id = $1::uuid
"""

FIND_NEXT_TASK = """
  SELECT
    task_id, task_type, sequence_order, assigned_agent, priority, payload
  FROM tasks
  WHERE mission_id = $1::uuid
    AND status IN ('pending', 'ready')
  ORDER BY sequence_order ASC
  LIMIT 1
"""

ACTIVATE_TASK = """
  UPDATE tasks
  SET status     = 'active',
      started_at = NOW()
  WHERE task_id = $1::uuid
"""


# ─────────────────────────────────────────────
# warehouse_locations
# ─────────────────────────────────────────────

FIND_NEAREST_CHARGER = """
  SELECT
    shelf_id, zone, x, y,
    -- Euclidean squared distance; sqrt would be redundant for ordering
    ((x - $1) * (x - $1) + (y - $2) * (y - $2)) AS dist_sq
  FROM warehouse_locations
  WHERE location_type = 'charger'
  ORDER BY dist_sq ASC
  LIMIT 1
"""

FIND_LOCATION_BY_SHELF = """
  SELECT shelf_id, zone, x, y
  FROM warehouse_locations
  WHERE shelf_id = $1
"""


# ─────────────────────────────────────────────
# anomaly_records
# ─────────────────────────────────────────────

INSERT_ANOMALY = """
  INSERT INTO anomaly_records (
    robot_id, anomaly_type, severity, detected_by,
    related_event_id, description, state_snapshot,
    resolved, created_at
  )
  VALUES (
    $1, $2, $3, $4,
    $5, $6, $7::jsonb,
    FALSE, NOW()
  )
  RETURNING anomaly_id
"""


# ─────────────────────────────────────────────
# Navigation 
# ─────────────────────────────────────────────

COUNT_RECENT_BLOCKAGE_EVENTS = """
	SELECT
		COUNT(*)                              AS event_count,
		MIN(created_at)                       AS first_at,
		MAX(created_at)                       AS last_at,
		ARRAY_AGG(event_type ORDER BY created_at) AS event_types
	FROM robot_events
	WHERE robot_id  = $1
		AND event_type IN ('path_blocked', 'navigation_failed')
		AND created_at >= NOW() - ($2 || ' seconds')::interval
		AND id != $3                       -- exclude the triggering event itself
"""