"""
EventRepository.

Async persistence layer for the event system. Owns:
  - inserting new event rows
  - dedup lookups + collapse increments
  - lifecycle status transitions
  - emitting Postgres NOTIFY for cross-process orchestrator wakeup
  - expiring stale pending events

The repository accepts a pre-existing asyncpg pool (injected) rather
than managing its own connection — the aggregator already has a pool
for robot_state writes, and we want them to share it.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import asyncpg

from event_system.persistence import queries
from event_system.schemas.models import Event

logger = logging.getLogger(__name__)


class EventRepository:

  def __init__(self, pool: asyncpg.Pool):
    self._pool = pool

  # ─────────────────────────────────────────────
  # Insert + dedup
  # ─────────────────────────────────────────────

  async def insert(self, event: Event) -> int:
    """Insert a new event row. Mutates `event.event_id` with the assigned id."""
    async with self._pool.acquire() as conn:
      row = await conn.fetchrow(
        queries.INSERT_EVENT,
        event.robot_id,
        event.event_type,
        event.severity,
        event.source_component,
        json.dumps(event.payload),
        event.dedup_key,
        event.created_at,
      )
    event.event_id = row["id"]
    return row["id"]

  async def find_latest_by_dedup_key(self, dedup_key: str) -> Optional[dict]:
    async with self._pool.acquire() as conn:
      row = await conn.fetchrow(queries.FIND_LATEST_BY_DEDUP_KEY, dedup_key)
    return dict(row) if row else None

  async def bump_dedup(self, event_id: int) -> None:
    async with self._pool.acquire() as conn:
      await conn.execute(queries.BUMP_DEDUP, event_id)

  # ─────────────────────────────────────────────
  # Lifecycle transitions
  # Each method returns True iff the row actually transitioned (the WHERE
  # clause guards against double-transitions and out-of-order updates).
  # ─────────────────────────────────────────────

  async def mark_dispatched(self, event_id: int) -> bool:
    return await self._exec_returning_rowcount(queries.MARK_DISPATCHED, event_id)

  async def mark_in_progress(self, event_id: int, workflow_id: str) -> bool:
    return await self._exec_returning_rowcount(queries.MARK_IN_PROGRESS, event_id, workflow_id)

  async def mark_completed(self, event_id: int) -> bool:
    return await self._exec_returning_rowcount(queries.MARK_COMPLETED, event_id)

  async def mark_failed(self, event_id: int) -> bool:
    return await self._exec_returning_rowcount(queries.MARK_FAILED, event_id)

  async def expire_stale(self, ttl_seconds: int) -> int:
    """Mark any 'pending' rows older than ttl as 'expired'. Returns count."""
    async with self._pool.acquire() as conn:
      rows = await conn.fetch(queries.EXPIRE_STALE_PENDING, str(ttl_seconds))
    return len(rows)

  # ─────────────────────────────────────────────
  # NOTIFY
  # ─────────────────────────────────────────────

  async def notify_new_event(self, event_id: int) -> None:
    async with self._pool.acquire() as conn:
      await conn.execute(queries.NOTIFY_NEW_EVENT, str(event_id))

  # ─────────────────────────────────────────────
  # Helpers
  # ─────────────────────────────────────────────

  async def _exec_returning_rowcount(self, sql: str, *args) -> bool:
    async with self._pool.acquire() as conn:
      tag = await conn.execute(sql, *args)
    # asyncpg returns tags like "UPDATE 1" / "UPDATE 0"
    try:
      return int(tag.split()[-1]) > 0
    except (ValueError, IndexError):
      return False
