"""
Shared async DB helpers used by workflow nodes.

Each helper is small, side-effect-only, and uses the asyncpg pool that
the runtime hands every graph at compile time. Nothing here knows
about LangGraph — these are plain async functions a node can call.

Why a separate module: the same write (e.g. insert_agent_command)
appears in multiple workflows. Centralizing keeps the SQL surface
consistent and parameter order stable.
"""

import json
import uuid
from typing import Optional

import asyncpg

from workflows import queries


# ─────────────────────────────────────────────
# agent_commands
# ─────────────────────────────────────────────

async def insert_agent_command(
  pool: asyncpg.Pool,
  *,
  robot_id: str,
  source_agent: str,
  command_type: str,
  payload: dict,
  priority: int = 0,
  mission_id: Optional[str] = None,
) -> str:
  async with pool.acquire() as conn:
    row = await conn.fetchrow(
      queries.INSERT_AGENT_COMMAND,
      mission_id,
      robot_id,
      source_agent,
      command_type,
      json.dumps(payload),
      priority,
    )
  return str(row["command_id"])


# ─────────────────────────────────────────────
# missions
# ─────────────────────────────────────────────

async def update_mission_status(pool: asyncpg.Pool, mission_id: str, status: str) -> None:
  async with pool.acquire() as conn:
    await conn.execute(queries.UPDATE_MISSION_STATUS, mission_id, status)


async def complete_mission(pool: asyncpg.Pool, mission_id: str) -> None:
  async with pool.acquire() as conn:
    await conn.execute(queries.COMPLETE_MISSION, mission_id)


async def claim_pending_mission(pool: asyncpg.Pool, robot_id: str) -> Optional[dict]:
  """
  Atomically find a pending mission and assign it to `robot_id`.

  Uses FOR UPDATE SKIP LOCKED so two scheduling workflows running for
  two idle robots can't grab the same mission.
  """
  async with pool.acquire() as conn:
    async with conn.transaction():
      row = await conn.fetchrow(queries.FIND_PENDING_UNASSIGNED_MISSION)
      if row is None:
        return None
      await conn.execute(queries.ASSIGN_MISSION_TO_ROBOT, row["mission_id"], robot_id)
      return _row_to_dict(row)


# ─────────────────────────────────────────────
# tasks
# ─────────────────────────────────────────────

async def complete_task(pool: asyncpg.Pool, task_id: str) -> None:
  async with pool.acquire() as conn:
    await conn.execute(queries.COMPLETE_TASK, task_id)


async def find_next_task(pool: asyncpg.Pool, mission_id: str) -> Optional[dict]:
  async with pool.acquire() as conn:
    row = await conn.fetchrow(queries.FIND_NEXT_TASK, mission_id)
  return _row_to_dict(row)


async def activate_task(pool: asyncpg.Pool, task_id: str) -> None:
  async with pool.acquire() as conn:
    await conn.execute(queries.ACTIVATE_TASK, task_id)


# ─────────────────────────────────────────────
# warehouse_locations
# ─────────────────────────────────────────────

async def find_nearest_charger(
  pool: asyncpg.Pool,
  x: Optional[float],
  y: Optional[float],
) -> Optional[dict]:
  if x is None or y is None:
    # No position → pick *any* charger (still deterministic by shelf_id).
    x = 0.0
    y = 0.0
  async with pool.acquire() as conn:
    row = await conn.fetchrow(queries.FIND_NEAREST_CHARGER, x, y)
  return _row_to_dict(row)


async def find_location(pool: asyncpg.Pool, shelf_id: str) -> Optional[dict]:
  async with pool.acquire() as conn:
    row = await conn.fetchrow(queries.FIND_LOCATION_BY_SHELF, shelf_id)
  return _row_to_dict(row)


# ─────────────────────────────────────────────
# anomaly_records
# ─────────────────────────────────────────────

async def insert_anomaly(
  pool: asyncpg.Pool,
  *,
  robot_id: str,
  anomaly_type: str,
  severity: str,
  detected_by: str,
  related_event_id: Optional[int],
  description: str,
  state_snapshot: Optional[dict],
) -> str:
  async with pool.acquire() as conn:
    row = await conn.fetchrow(
      queries.INSERT_ANOMALY,
      robot_id,
      anomaly_type,
      severity,
      detected_by,
      related_event_id,
      description,
      json.dumps(state_snapshot or {}),
    )
  return str(row["anomaly_id"])


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
async def count_recent_blockage_events(
  pool: asyncpg.Pool,
  robot_id: str,
  window_s: int,
  exclude_event_id: int,
) -> dict:
  async with pool.acquire() as conn:
    row = await conn.fetchrow(
      queries.COUNT_RECENT_BLOCKAGE_EVENTS,
      robot_id,
      str(window_s),
      exclude_event_id,
    )
  return _row_to_dict(row)

def _row_to_dict(row) -> Optional[dict]:
  if row is None:
    return None
  out = {}
  for key, value in row.items():
    if hasattr(value, "isoformat"):
      out[key] = value.isoformat()
    elif isinstance(value, uuid.UUID) or type(value).__name__ == "UUID":
      out[key] = str(value)
    elif isinstance(value, str) and key in ("metadata", "payload"):
      try:
        out[key] = json.loads(value)
      except (ValueError, TypeError):
        out[key] = value
    else:
      out[key] = value
  return out
