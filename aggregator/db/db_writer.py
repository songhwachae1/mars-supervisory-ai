import json
import logging
from typing import Optional

import asyncpg

from aggregator.schemas.models import RobotState, RobotEvent
from aggregator.db import queries

logger = logging.getLogger(__name__)


class DBWriter:
  """
  Async PostgreSQL writer for the blackboard.

  Writes to:
  - robot_state  : upsert current semantic state
  - robot_events : insert new events

  Uses asyncpg for non-blocking I/O so it does not stall
  the ROS2 subscription callbacks.

  SQL is defined in queries.py — this class handles only
  connection management and execution.
  """

  def __init__(self, dsn: str):
    self._dsn = dsn
    self._pool: Optional[asyncpg.Pool] = None

  async def connect(self) -> None:
    self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
    logger.info("DBWriter connected to PostgreSQL")

  async def close(self) -> None:
    if self._pool:
      await self._pool.close()
      logger.info("DBWriter pool closed")

  # ─────────────────────────────────────────────
  # Robot State
  # ─────────────────────────────────────────────

  async def upsert_robot_state(self, state: RobotState) -> None:
    if not self._pool:
      logger.error("DBWriter not connected")
      return

    try:
      async with self._pool.acquire() as conn:
        await conn.execute(
          queries.UPSERT_ROBOT_STATE,
          state.robot_id,
          state.robot_name,
          state.x, state.y, state.theta,
          state.current_zone,
          state.battery_pct,
          state.operational_status,
          state.navigation_status,
          state.current_mission_id,
          state.current_task_id,
          state.last_heartbeat,
          state.health_score,
        )
    except Exception as e:
      logger.error(f"upsert_robot_state failed for {state.robot_id}: {e}")

  # ─────────────────────────────────────────────
  # Robot Events
  # ─────────────────────────────────────────────

  async def insert_event(self, event: RobotEvent) -> None:
    if not self._pool:
      logger.error("DBWriter not connected")
      return

    try:
      async with self._pool.acquire() as conn:
        await conn.execute(
          queries.INSERT_ROBOT_EVENT,
          event.robot_id,
          event.event_type,
          event.severity,
          event.source_component,
          json.dumps(event.payload),
          event.created_at,
        )
      logger.info(f"Event inserted: {event.event_type} for robot {event.robot_id}")
    except Exception as e:
      logger.error(f"insert_event failed for {event.robot_id}: {e}")
