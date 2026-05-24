"""
All SQL queries for the aggregator blackboard writes.

Kept separate from DBWriter so that:
- queries are easy to read and review in isolation
- DBWriter stays focused on connection/execution logic
- queries can be tested or swapped without touching DB plumbing
"""


# ─────────────────────────────────────────────
# robot_state
# ─────────────────────────────────────────────

UPSERT_ROBOT_STATE = """
  INSERT INTO robot_state (
    robot_id,
    robot_name,
    x,
    y,
    theta,
    current_zone,
    battery_pct,
    operational_status,
    navigation_status,
    current_mission_id,
    current_task_id,
    last_heartbeat,
    health_score,
    updated_at
  )
  VALUES (
    $1, $2,
    $3, $4, $5,
    $6,
    $7,
    $8,
    $9,
    $10::uuid,
    $11::uuid,
    $12,
    $13,
    NOW()
  )
  ON CONFLICT (robot_id) DO UPDATE SET
    robot_name         = EXCLUDED.robot_name,
    x                  = EXCLUDED.x,
    y                  = EXCLUDED.y,
    theta              = EXCLUDED.theta,
    current_zone       = EXCLUDED.current_zone,
    battery_pct        = EXCLUDED.battery_pct,
    operational_status = EXCLUDED.operational_status,
    navigation_status  = EXCLUDED.navigation_status,
    current_mission_id = EXCLUDED.current_mission_id,
    current_task_id    = EXCLUDED.current_task_id,
    last_heartbeat     = EXCLUDED.last_heartbeat,
    health_score       = EXCLUDED.health_score,
    updated_at         = NOW()
"""


# ─────────────────────────────────────────────
# robot_events
# ─────────────────────────────────────────────

INSERT_ROBOT_EVENT = """
  INSERT INTO robot_events (
    robot_id,
    event_type,
    severity,
    source_component,
    payload,
    processed,
    created_at
  )
  VALUES (
    $1, $2, $3, $4, $5::jsonb, FALSE, $6
  )
"""
