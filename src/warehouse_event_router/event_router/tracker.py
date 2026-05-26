"""
ExecutionTracker.

Once a workflow ends, its row in workflow_execution flips to
'completed' or 'failed'. The triggering robot_events row, however,
is still 'in_progress' until something updates it.

The tracker bridges that gap:

  workflow_execution.status = 'completed' → robot_events.status = 'completed'
  workflow_execution.status = 'failed'    → robot_events.status = 'failed'

Two ways to call this:

  (a) reconcile() — sweep mode. Cheap, idempotent, run on a timer.
  (b) mark_completed(event_id) / mark_failed(event_id) — direct mode,
      callable from a LangGraph terminal node when LangGraph is wired up.

The tracker is also where the legacy `processed` boolean gets set
(through the COMPLETE_EVENT / FAIL_EVENT queries), satisfying the
"mark event processed" responsibility.
"""

import logging

import asyncpg

from event_router import queries

logger = logging.getLogger(__name__)


class ExecutionTracker:

  def __init__(self, pool: asyncpg.Pool):
    self._pool = pool

  # ─────────────────────────────────────────────
  # Sweep reconciliation
  # ─────────────────────────────────────────────

  async def reconcile(self) -> int:
    """
    Find workflows that finished while their event row is still
    in_progress, and reconcile the event status to match the workflow.
    Returns the number of events updated.
    """
    rows = []
    async with self._pool.acquire() as conn:
      rows = await conn.fetch(queries.SELECT_FINISHED_WORKFLOWS_WITH_OPEN_EVENTS)

    if not rows:
      return 0

    updated = 0
    for row in rows:
      wf_status = row["workflow_status"]
      event_id  = row["event_id"]
      if wf_status == "completed":
        ok = await self.mark_completed(event_id)
      elif wf_status == "failed":
        ok = await self.mark_failed(event_id)
      else:
        continue
      if ok:
        updated += 1

    if updated:
      logger.info(f"Tracker: reconciled {updated} event(s) from workflow terminals")
    return updated

  # ─────────────────────────────────────────────
  # Direct API (for the LangGraph terminal callback)
  # ─────────────────────────────────────────────

  async def mark_completed(self, event_id: int) -> bool:
    return await self._exec(queries.COMPLETE_EVENT, event_id)

  async def mark_failed(self, event_id: int) -> bool:
    return await self._exec(queries.FAIL_EVENT, event_id)

  # ─────────────────────────────────────────────
  # Helper
  # ─────────────────────────────────────────────

  async def _exec(self, sql: str, *args) -> bool:
    async with self._pool.acquire() as conn:
      tag = await conn.execute(sql, *args)
    try:
      return int(tag.split()[-1]) > 0
    except (ValueError, IndexError):
      return False
