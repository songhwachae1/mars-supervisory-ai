"""
LifecycleManager.

Orchestrates event status transitions. Wraps the repository so that all
status changes go through a single guarded API instead of being scattered
across the codebase.

Transition table (see schemas.statuses.ALLOWED_TRANSITIONS):

  pending     → dispatched | expired | suppressed
  dispatched  → in_progress | failed  | expired
  in_progress → completed   | failed
  (terminal states have no outgoing edges)

Each public method validates the transition against the in-memory Event
copy AND lets the repository enforce it again in the WHERE clause —
double validation guards against concurrent writers (e.g. two orchestrator
workers picking up the same event).
"""

import logging
from datetime import datetime
from typing import Optional

from event_system.persistence.repository import EventRepository
from event_system.schemas.models import Event
from event_system.schemas.statuses import (
  ALLOWED_TRANSITIONS,
  EventStatus,
  TERMINAL_STATES,
)

logger = logging.getLogger(__name__)


class IllegalTransition(Exception):
  pass


class LifecycleManager:

  def __init__(self, repository: EventRepository):
    self._repo = repository

  # ─────────────────────────────────────────────
  # Forward transitions
  # ─────────────────────────────────────────────

  async def mark_dispatched(self, event: Event) -> bool:
    self._require_transition(event.status, EventStatus.DISPATCHED.value)
    ok = await self._repo.mark_dispatched(event.event_id)
    if ok:
      event.status = EventStatus.DISPATCHED.value
      event.dispatched_at = datetime.utcnow()
      event.last_updated_at = event.dispatched_at
    return ok

  async def mark_in_progress(self, event: Event, workflow_id: str) -> bool:
    self._require_transition(event.status, EventStatus.IN_PROGRESS.value)
    ok = await self._repo.mark_in_progress(event.event_id, workflow_id)
    if ok:
      event.status = EventStatus.IN_PROGRESS.value
      event.workflow_id = workflow_id
      event.last_updated_at = datetime.utcnow()
    return ok

  async def mark_completed(self, event: Event) -> bool:
    self._require_transition(event.status, EventStatus.COMPLETED.value)
    ok = await self._repo.mark_completed(event.event_id)
    if ok:
      event.status = EventStatus.COMPLETED.value
      event.completed_at = datetime.utcnow()
      event.last_updated_at = event.completed_at
    return ok

  async def mark_failed(self, event: Event) -> bool:
    self._require_transition(event.status, EventStatus.FAILED.value)
    ok = await self._repo.mark_failed(event.event_id)
    if ok:
      event.status = EventStatus.FAILED.value
      event.completed_at = datetime.utcnow()
      event.last_updated_at = event.completed_at
    return ok

  # ─────────────────────────────────────────────
  # Expiry sweeper — invoked by a background task
  # ─────────────────────────────────────────────

  async def expire_stale(self, ttl_seconds: int) -> int:
    count = await self._repo.expire_stale(ttl_seconds)
    if count:
      logger.warning(f"Lifecycle: expired {count} stale pending events (>{ttl_seconds}s)")
    return count

  # ─────────────────────────────────────────────
  # Guards
  # ─────────────────────────────────────────────

  @staticmethod
  def _require_transition(current: str, target: str) -> None:
    if current in TERMINAL_STATES:
      raise IllegalTransition(f"event is terminal ({current}); cannot move to {target}")
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
      raise IllegalTransition(f"{current} → {target} is not a valid transition")
