"""
EventClaimer.

Atomically claims a batch of unrouted events from PostgreSQL.

Locking strategy (read top-to-bottom):

  1. BEGIN transaction
  2. SELECT ... FOR UPDATE SKIP LOCKED
       - SKIP LOCKED lets multiple router instances run concurrently;
         each picks a disjoint set of events.
       - LIMIT keeps the transaction short and the held lock count low.
  3. For each row, UPDATE status='in_progress'.
       - From this moment, the soft lock is the row's own status field,
         which our claim query filters on. Another router instance
         cannot re-claim the row.
  4. COMMIT — releases the row-level locks.

After commit, the claimer returns the claimed events. The launcher
then assigns a workflow_id and links it back via a separate UPDATE.

Why split it: keeping the claim TX free of business logic (workflow
selection, input building) means it stays milliseconds long, which is
the only way SKIP LOCKED scales.
"""

import json
import logging
from typing import List

import asyncpg

from event_router import queries
from event_router.models import ClaimedEvent

logger = logging.getLogger(__name__)


class EventClaimer:

  def __init__(self, pool: asyncpg.Pool):
    self._pool = pool

  async def claim_batch(self, batch_size: int) -> List[ClaimedEvent]:
    """
    Claim up to `batch_size` events. Returns an empty list if nothing
    is available. Never blocks waiting for a lock — SKIP LOCKED returns
    immediately past contended rows.
    """
    claimed: List[ClaimedEvent] = []

    async with self._pool.acquire() as conn:
      async with conn.transaction():
        rows = await conn.fetch(queries.CLAIM_BATCH, batch_size)

        for row in rows:
          updated = await conn.execute(
            queries.MARK_IN_PROGRESS_NO_WORKFLOW,
            row["id"],
          )
          if not _rowcount_ok(updated):
            # Status moved out from under us — shouldn't happen given
            # SKIP LOCKED + the WHERE-clause guard, but be defensive.
            logger.warning(
              f"Claim: event_id={row['id']} no longer claimable "
              f"(status changed mid-transaction)"
            )
            continue

          claimed.append(_row_to_claimed_event(row))

    if claimed:
      logger.info(f"Claimed {len(claimed)} event(s) for routing")
    return claimed


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _row_to_claimed_event(row) -> ClaimedEvent:
  payload = row["payload"]
  if isinstance(payload, str):
    # asyncpg returns JSONB as str unless a codec is registered.
    try:
      payload = json.loads(payload)
    except (ValueError, TypeError):
      payload = {}
  elif payload is None:
    payload = {}

  return ClaimedEvent(
    event_id=row["id"],
    robot_id=row["robot_id"],
    event_type=row["event_type"],
    severity=row["severity"],
    source_component=row["source_component"],
    payload=payload,
  )


def _rowcount_ok(tag: str) -> bool:
  try:
    return int(tag.split()[-1]) > 0
  except (ValueError, IndexError):
    return False
