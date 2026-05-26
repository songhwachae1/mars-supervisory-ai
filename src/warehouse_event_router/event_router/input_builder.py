"""
WorkflowInputBuilder.

Builds the deterministic initial state for a LangGraph workflow.

Input = the triggering event + a snapshot of the blackboard rows the
workflow most commonly needs to start work:

  - robot_state    : current semantic state of the robot
  - active_mission : the robot's current mission, if any

That's it. No reasoning, no joins-of-joins, no rolled-up history. The
workflow itself is responsible for fetching anything else it needs.

The builder reads, does not write.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import asyncpg

from event_router import queries
from event_router.models import ClaimedEvent, WorkflowInput

logger = logging.getLogger(__name__)


class WorkflowInputBuilder:

  def __init__(self, pool: asyncpg.Pool):
    self._pool = pool

  async def build(self, event: ClaimedEvent) -> WorkflowInput:
    robot_state    = await self._fetch_robot_state(event.robot_id)
    active_mission = await self._fetch_active_mission(event.robot_id)

    return WorkflowInput(
      event=event,
      robot_state=robot_state,
      active_mission=active_mission,
    )

  # ─────────────────────────────────────────────
  # Fetchers
  # ─────────────────────────────────────────────

  async def _fetch_robot_state(self, robot_id: str) -> Optional[dict]:
    async with self._pool.acquire() as conn:
      row = await conn.fetchrow(queries.SELECT_ROBOT_STATE, robot_id)
    return _row_to_dict(row)

  async def _fetch_active_mission(self, robot_id: str) -> Optional[dict]:
    async with self._pool.acquire() as conn:
      row = await conn.fetchrow(queries.SELECT_ACTIVE_MISSION, robot_id)
    return _row_to_dict(row)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _row_to_dict(row) -> Optional[dict]:
  if row is None:
    return None

  out = {}
  for key, value in row.items():
    if isinstance(value, datetime):
      out[key] = value.isoformat()
    elif isinstance(value, str) and key in ("metadata", "payload"):
      # JSONB may arrive as str depending on codec config.
      try:
        out[key] = json.loads(value)
      except (ValueError, TypeError):
        out[key] = value
    else:
      out[key] = value
  return out
