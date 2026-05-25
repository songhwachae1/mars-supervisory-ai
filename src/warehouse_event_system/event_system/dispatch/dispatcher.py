"""
EventDispatcher.

Once an event is persisted, the dispatcher notifies consumers. There are
two delivery mechanisms in parallel:

  1. In-process subscribers
     Async callables registered via `subscribe()`. Fired in the order
     they were registered. A misbehaving subscriber cannot prevent the
     others from running.

  2. Postgres NOTIFY (channel: robot_events_new)
     Lets an orchestrator running in a separate process LISTEN for new
     events without polling. The payload is the event id.

Both fire on every dispatch — they are not exclusive. Use the in-process
path when orchestrator and event_system share a process; use NOTIFY for
the typical case where they don't.

After successful dispatch, the dispatcher transitions the event's
status pending → dispatched via the LifecycleManager.
"""

import asyncio
import logging
from typing import Awaitable, Callable, List

from event_system.lifecycle.manager import LifecycleManager
from event_system.persistence.repository import EventRepository
from event_system.schemas.models import Event

logger = logging.getLogger(__name__)


EventSubscriber = Callable[[Event], Awaitable[None]]


class EventDispatcher:

  def __init__(self, repository: EventRepository, lifecycle: LifecycleManager):
    self._repo = repository
    self._lifecycle = lifecycle
    self._subscribers: List[EventSubscriber] = []

  # ─────────────────────────────────────────────
  # Subscription API
  # ─────────────────────────────────────────────

  def subscribe(self, handler: EventSubscriber) -> None:
    self._subscribers.append(handler)

  def unsubscribe(self, handler: EventSubscriber) -> None:
    try:
      self._subscribers.remove(handler)
    except ValueError:
      pass

  # ─────────────────────────────────────────────
  # Dispatch
  # ─────────────────────────────────────────────

  async def dispatch(self, event: Event) -> None:
    """
    Fire NOTIFY and all in-process subscribers, then mark dispatched.

    NOTIFY is sent before the lifecycle update so that an external
    orchestrator that responds instantly to NOTIFY observes the row in
    'pending' (its own ACCEPT will move it to 'in_progress' from there).
    """
    if event.event_id is None:
      logger.error("Cannot dispatch event with no event_id — was it persisted?")
      return

    await self._notify_external(event)
    await self._fan_out_local(event)
    await self._lifecycle.mark_dispatched(event)
    logger.info(f"Dispatched event_id={event.event_id} type={event.event_type} robot={event.robot_id}")

  # ─────────────────────────────────────────────
  # Internal
  # ─────────────────────────────────────────────

  async def _notify_external(self, event: Event) -> None:
    try:
      await self._repo.notify_new_event(event.event_id)
    except Exception as e:
      logger.error(f"NOTIFY failed for event_id={event.event_id}: {e}")

  async def _fan_out_local(self, event: Event) -> None:
    if not self._subscribers:
      return
    # Run all subscribers concurrently; isolate failures.
    results = await asyncio.gather(
      *(self._safe_call(s, event) for s in self._subscribers),
      return_exceptions=True,
    )
    for sub, res in zip(self._subscribers, results):
      if isinstance(res, Exception):
        logger.error(f"Subscriber {sub} raised: {res}")

  @staticmethod
  async def _safe_call(handler: EventSubscriber, event: Event):
    return await handler(event)
