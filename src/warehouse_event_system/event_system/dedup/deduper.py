"""
Deduper.

Decides whether a freshly-built event should be:

  (a) inserted as a new row    → DedupDecision.INSERT
  (b) suppressed, collapsing onto an existing open row → DedupDecision.SUPPRESS

The decision is made against persisted state (robot_events) because the
event system can be restarted between events and we still want the new
process to recognize an open event from the previous one.

Rule:
  If there is an existing row with the same dedup_key whose status is
  in OPEN_STATES, suppress. Bump dedup_count + last_updated_at on the
  existing row. Otherwise insert.

Optional TTL debounce:
  Even if the previous row is in a terminal state, suppress if it was
  last touched within `debounce_seconds`. This handles flapping at the
  semantic edge (status oscillating across a threshold). Default: 5s.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from event_system.dedup.fingerprint import fingerprint
from event_system.schemas.models import Event
from event_system.schemas.statuses import OPEN_STATES

logger = logging.getLogger(__name__)


class DedupDecision(str, Enum):
  INSERT   = "insert"
  SUPPRESS = "suppress"


@dataclass
class DedupResult:
  decision: DedupDecision
  # When suppressing, the id of the open row that absorbed this event.
  absorbed_into_event_id: Optional[int] = None


class Deduper:
  """
  Stateless logic; delegates persistence reads/writes to a repository.

  The repository is injected so this class can be unit-tested without a
  database.
  """

  def __init__(self, repository, debounce_seconds: float = 5.0):
    self._repo = repository
    self._debounce = timedelta(seconds=debounce_seconds)

  async def check(self, event: Event) -> DedupResult:
    event.dedup_key = fingerprint(event)

    existing = await self._repo.find_latest_by_dedup_key(event.dedup_key)

    if existing is None:
      return DedupResult(decision=DedupDecision.INSERT)

    if existing["status"] in OPEN_STATES:
      # Same problem is already in flight — collapse onto it.
      await self._repo.bump_dedup(existing["id"])
      logger.info(
        f"Dedup: suppressed {event.event_type} for {event.robot_id} "
        f"(absorbed into event_id={existing['id']})"
      )
      return DedupResult(
        decision=DedupDecision.SUPPRESS,
        absorbed_into_event_id=existing["id"],
      )

    # Terminal — but still within debounce window?
    last = existing.get("last_updated_at")
    if last is not None and datetime.utcnow() - last < self._debounce:
      await self._repo.bump_dedup(existing["id"])
      logger.info(
        f"Dedup: debounced {event.event_type} for {event.robot_id} "
        f"(within {self._debounce.total_seconds()}s of event_id={existing['id']})"
      )
      return DedupResult(
        decision=DedupDecision.SUPPRESS,
        absorbed_into_event_id=existing["id"],
      )

    return DedupResult(decision=DedupDecision.INSERT)
