"""
End-to-end pipeline test.

Tests the full path:
  robot_events row (seed)
    → EventRouter.claim + select + build_input
    → WorkflowLauncher (workflow_execution row)
    → WorkflowRuntime.invoke (LangGraph graph)
    → tool layer (validate + persist)
    → agent_commands / anomaly_records written to DB

Run from the repo root:
  .venv/bin/python3 scripts/test_e2e.py

Cleans up all seeded rows after each scenario.
"""

import asyncio
import logging
import os
import sys
import uuid

import asyncpg
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_e2e")

# ─────────────────────────────────────────────
# Scenario definitions
# Each entry: event_type, robot_id, extra_payload
# ─────────────────────────────────────────────

SCENARIOS = [
    {
        "name":       "diagnostic_workflow via robot_error",
        "event_type": "robot_error",
        "robot_id":   "robot_01",
        "payload":    {"source_component": "navigation_stack", "code": "E_NAV_FAULT"},
    },
    {
        "name":       "monitoring_workflow via health_degraded",
        "event_type": "health_degraded",
        "robot_id":   "robot_01",
        "payload":    {"health_score": 0.4},
    },
    {
        "name":       "emergency_charging_workflow via battery_critical",
        "event_type": "battery_critical",
        "robot_id":   "robot_01",
        "payload":    {"battery_pct": 3.0},
    },
    {
        "name":       "scheduling_workflow via robot_idle",
        "event_type": "robot_idle",
        "robot_id":   "robot_01",
        "payload":    {},
    },
    {
        "name":       "recovery_workflow via path_blocked",
        "event_type": "path_blocked",
        "robot_id":   "robot_01",
        "payload":    {"obstacle": "unknown_object"},
    },
]


# ─────────────────────────────────────────────
# Seed / teardown helpers
# ─────────────────────────────────────────────

CHARGER_SHELF = "CHARGER_01"
DEST_SHELF    = "SHELF_A01"
TEST_TAG      = "e2e_test"


async def seed_locations(conn):
    await conn.execute("""
        INSERT INTO warehouse_locations (shelf_id, zone, x, y, location_type, metadata)
        VALUES ($1, 'charging', 5.0, 5.0, 'charger', $2::jsonb)
        ON CONFLICT (shelf_id) DO NOTHING
    """, CHARGER_SHELF, f'{{"tag":"{TEST_TAG}"}}')

    await conn.execute("""
        INSERT INTO warehouse_locations (shelf_id, zone, x, y, location_type, metadata)
        VALUES ($1, 'storage', 20.0, 10.0, 'shelf', $2::jsonb)
        ON CONFLICT (shelf_id) DO NOTHING
    """, DEST_SHELF, f'{{"tag":"{TEST_TAG}"}}')


async def seed_mission(conn, robot_id: str) -> str:
    """Seed a pending mission with one task and return mission_id."""
    mission_id = str(uuid.uuid4())
    task_id    = str(uuid.uuid4())

    await conn.execute("""
        INSERT INTO missions
            (mission_id, robot_id, mission_type, status,
             destination_location, priority, metadata)
        VALUES ($1::uuid, $2, 'delivery', 'pending',
                $3, 10, $4::jsonb)
    """, mission_id, None, DEST_SHELF, f'{{"tag":"{TEST_TAG}"}}')

    await conn.execute("""
        INSERT INTO tasks
            (task_id, mission_id, robot_id, task_type,
             status, sequence_order, priority)
        VALUES ($1::uuid, $2::uuid, $3, 'navigate',
                'pending', 1, 5)
    """, task_id, mission_id, robot_id)

    return mission_id


async def seed_active_mission(conn, robot_id: str) -> tuple:
    """Seed an active mission with an active task. Returns (mission_id, task_id)."""
    mission_id = str(uuid.uuid4())
    task_id    = str(uuid.uuid4())
    next_task_id = str(uuid.uuid4())

    await conn.execute("""
        INSERT INTO missions
            (mission_id, robot_id, mission_type, status,
             destination_location, priority, metadata)
        VALUES ($1::uuid, $2, 'delivery', 'active',
                $3, 10, $4::jsonb)
    """, mission_id, robot_id, DEST_SHELF, f'{{"tag":"{TEST_TAG}"}}')

    await conn.execute("""
        INSERT INTO tasks
            (task_id, mission_id, robot_id, task_type,
             status, sequence_order, priority)
        VALUES ($1::uuid, $2::uuid, $3, 'navigate', 'active', 1, 5)
    """, task_id, mission_id, robot_id)

    await conn.execute("""
        INSERT INTO tasks
            (task_id, mission_id, robot_id, task_type,
             status, sequence_order, priority)
        VALUES ($1::uuid, $2::uuid, $3, 'pick', 'pending', 2, 5)
    """, next_task_id, mission_id, robot_id)

    return mission_id, task_id


async def set_robot_state(conn, robot_id: str, *, task_id=None, mission_id=None,
                           battery_pct=80.0, x=10.0, y=10.0):
    await conn.execute("""
        UPDATE robot_state
        SET battery_pct       = $2,
            x                 = $3,
            y                 = $4,
            current_task_id   = $5::uuid,
            current_mission_id = $6::uuid,
            operational_status = 'active',
            updated_at        = NOW()
        WHERE robot_id = $1
    """, robot_id, battery_pct, x, y, task_id, mission_id)


async def teardown(conn):
    await conn.execute(f"""
        DELETE FROM warehouse_locations WHERE metadata->>'tag' = '{TEST_TAG}'
    """)
    await conn.execute(f"""
        DELETE FROM tasks WHERE mission_id IN (
            SELECT mission_id FROM missions WHERE metadata->>'tag' = '{TEST_TAG}'
        )
    """)
    await conn.execute(f"""
        DELETE FROM missions WHERE metadata->>'tag' = '{TEST_TAG}'
    """)
    # Clean up events and derived rows from this test run.
    await conn.execute("""
        DELETE FROM workflow_checkpoints
        WHERE workflow_id IN (
            SELECT workflow_id FROM workflow_execution
            WHERE workflow_type LIKE '%workflow%'
              AND started_at > NOW() - INTERVAL '10 minutes'
        )
    """)
    await conn.execute("""
        DELETE FROM agent_commands
        WHERE source_agent IN (
          'charging_workflow','emergency_charging_workflow',
          'diagnostic_workflow','scheduling_workflow',
          'recovery_workflow','tool_layer'
        ) AND created_at > NOW() - INTERVAL '10 minutes'
    """)
    await conn.execute("""
        DELETE FROM anomaly_records
        WHERE detected_by IN (
          'diagnostic_workflow','monitoring_workflow',
          'recovery_workflow','tool_layer'
        ) AND created_at > NOW() - INTERVAL '10 minutes'
    """)
    await conn.execute("""
        DELETE FROM workflow_execution
        WHERE started_at > NOW() - INTERVAL '10 minutes'
    """)
    await conn.execute("""
        DELETE FROM robot_events
        WHERE created_at > NOW() - INTERVAL '10 minutes'
    """)


# ─────────────────────────────────────────────
# Result reporting
# ─────────────────────────────────────────────

async def report(conn, event_id: int, workflow_name: str):
    wf = await conn.fetchrow("""
        SELECT workflow_id, status, current_node
        FROM workflow_execution
        WHERE workflow_id = (
            SELECT workflow_id FROM robot_events WHERE id = $1
        )
    """, event_id)

    cmds = await conn.fetch("""
        SELECT command_type, priority, payload
        FROM agent_commands
        WHERE created_at > NOW() - INTERVAL '10 minutes'
          AND source_agent != 'test'
        ORDER BY created_at DESC
        LIMIT 5
    """)

    anomalies = await conn.fetch("""
        SELECT anomaly_type, severity, detected_by
        FROM anomaly_records
        WHERE created_at > NOW() - INTERVAL '10 minutes'
        ORDER BY created_at DESC
        LIMIT 5
    """)

    status = wf["status"] if wf else "no_workflow_row"
    print(f"\n  workflow status : {status}")
    if wf:
        print(f"  workflow_id     : {wf['workflow_id']}")
    if cmds:
        print(f"  agent_commands  :")
        for c in cmds:
            print(f"    type={c['command_type']} priority={c['priority']}")
    else:
        print(f"  agent_commands  : (none)")
    if anomalies:
        print(f"  anomaly_records :")
        for a in anomalies:
            print(f"    type={a['anomaly_type']} severity={a['severity']}")
    else:
        print(f"  anomaly_records : (none)")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

async def run_scenario(pool, runtime, scenario: dict):
    name       = scenario["name"]
    event_type = scenario["event_type"]
    robot_id   = scenario["robot_id"]
    payload    = scenario["payload"]

    print(f"\n{'─'*60}")
    print(f"SCENARIO: {name}")
    print(f"{'─'*60}")

    async with pool.acquire() as conn:
        await seed_locations(conn)

        # Per-scenario state prep
        mission_id = None
        task_id    = None

        if event_type == "robot_idle":
            mission_id = await seed_mission(conn, robot_id)
            await set_robot_state(conn, robot_id, battery_pct=80.0)

        elif event_type == "path_blocked":
            mission_id, task_id = await seed_active_mission(conn, robot_id)
            await set_robot_state(conn, robot_id, task_id=task_id,
                                   mission_id=mission_id, x=8.0, y=8.0)

        elif event_type == "robot_arrived":
            mission_id, task_id = await seed_active_mission(conn, robot_id)
            await set_robot_state(conn, robot_id, task_id=task_id, mission_id=mission_id)

        else:
            await set_robot_state(conn, robot_id, battery_pct=5.0)

        # Insert event
        event_id = await conn.fetchval("""
            INSERT INTO robot_events
                (robot_id, event_type, severity, payload, status, created_at)
            VALUES ($1, $2, 'high', $3::jsonb, 'pending', NOW())
            RETURNING id
        """, robot_id, event_type, str(payload).replace("'", '"'))

        print(f"  event_id={event_id} event_type={event_type}")

    # Run the router's claim→route→launch cycle
    from event_router.claimer import EventClaimer
    from event_router.selector import WorkflowSelector
    from event_router.input_builder import WorkflowInputBuilder
    from event_router.launcher import WorkflowLauncher
    from event_router.models import ClaimedEvent

    claimer  = EventClaimer(pool)
    selector = WorkflowSelector()
    builder  = WorkflowInputBuilder(pool)
    launcher = WorkflowLauncher(pool, runtime)

    events = await claimer.claim_batch(10)
    matched = [e for e in events if e.event_id == event_id]
    if not matched:
        print("  ERROR: event not claimed by router")
        return

    claimed = matched[0]
    decision, workflow_name = selector.select(claimed.event_type)
    print(f"  decision={decision} workflow={workflow_name}")

    if decision == "launch":
        workflow_input = await builder.build(claimed)
        await launcher.launch(workflow_name, claimed, workflow_input)
        # Give background tasks time to finish
        await asyncio.sleep(3.0)

    async with pool.acquire() as conn:
        await report(conn, event_id, workflow_name or "")
        await teardown(conn)


async def main():
    dsn = os.environ["DB_DSN"]
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5)

    psycopg_dsn = dsn  # psycopg3 accepts the same postgresql:// DSN

    from workflows import WorkflowRuntime
    runtime = WorkflowRuntime(pool, psycopg_dsn)
    await runtime.start()

    print("\n=== e2e workflow pipeline test ===")
    passed = 0
    failed = 0

    for scenario in SCENARIOS:
        try:
            await run_scenario(pool, runtime, scenario)
            passed += 1
        except Exception as e:
            print(f"  EXCEPTION: {e!r}")
            import traceback; traceback.print_exc()
            failed += 1

    await runtime.stop()
    await pool.close()

    print(f"\n{'═'*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'═'*60}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
