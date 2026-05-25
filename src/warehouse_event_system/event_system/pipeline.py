"""
EventPipeline — top-level orchestrator of the event system.

Stages, in order, per incoming state transition:

  1. detect    — StateTransitionDetector  →  list[EventCandidate]
  2. build     — EventBuilder              →  list[Event] (with severity assigned)
  3. dedup     — Deduper                   →  insert or suppress
  4. persist   — EventRepository.insert    →  assigns event_id
  5. dispatch  — EventDispatcher           →  NOTIFY + local subscribers + pending→dispatched
  6. lifecycle — LifecycleManager          →  future transitions driven by orchestrator

The pipeline is the only class an aggregator (or any state source) needs
to know about. All sub-components are wired by `build_default()`.
"""

import asyncio
import logging
from typing import List, Optional

import asyncpg

from event_system.construction.builder import EventBuilder
from event_system.dedup.deduper import Deduper, DedupDecision
from event_system.detection.detector import StateTransitionDetector
from event_system.dispatch.dispatcher import EventDispatcher, EventSubscriber
from event_system.lifecycle.manager import LifecycleManager
from event_system.persistence.repository import EventRepository
from event_system.schemas.models import Event, StateTransition
from event_system.severity.classifier import SeverityClassifier

logger = logging.getLogger(__name__)


class EventPipeline:

  def __init__(
    self,
    detector: StateTransitionDetector,
    builder: EventBuilder,
    deduper: Deduper,
    repository: EventRepository,
    dispatcher: EventDispatcher,
    lifecycle: LifecycleManager,
  ):
    self._detector  = detector
    self._builder   = builder
    self._deduper   = deduper
    self._repo      = repository
    self._dispatcher = dispatcher
    self._lifecycle = lifecycle

    self._expiry_task: Optional[asyncio.Task] = None

  # ─────────────────────────────────────────────
  # Convenience constructor
  # ─────────────────────────────────────────────

  @classmethod
  def build_default(cls, pool: asyncpg.Pool, debounce_seconds: float = 5.0) -> "EventPipeline":
    repository = EventRepository(pool)
    lifecycle  = LifecycleManager(repository)
    return cls(
      detector=StateTransitionDetector(),
      builder=EventBuilder(SeverityClassifier()),
      deduper=Deduper(repository, debounce_seconds=debounce_seconds),
      repository=repository,
      dispatcher=EventDispatcher(repository, lifecycle),
      lifecycle=lifecycle,
    )

  # ─────────────────────────────────────────────
  # Public API: submit a state transition
  # ─────────────────────────────────────────────

  async def submit(self, prev_state, new_state) -> List[Event]:
    """
    Process one state transition through the full pipeline.

    Returns the list of events that were actually persisted (suppressed
    ones are not included). The caller usually ignores the return value;
    it's exposed for tests and observability.
    """
    transition = StateTransition(robot_id=new_state.robot_id, prev=prev_state, new=new_state)
    candidates = self._detector.detect(transition)
    if not candidates:
      return []

    events = self._builder.build_many(candidates, new_state)
    persisted: List[Event] = []

    for event in events:
      try:
        if not await self._dedup_and_persist(event):
          continue
        persisted.append(event)
        await self._dispatcher.dispatch(event)
      except Exception as e:
        logger.error(
          f"Pipeline failure on {event.event_type}/{event.robot_id}: {e}"
        )

    return persisted

  # ─────────────────────────────────────────────
  # Subscriber registration (proxied to dispatcher)
  # ─────────────────────────────────────────────

  def subscribe(self, handler: EventSubscriber) -> None:
    self._dispatcher.subscribe(handler)

  # ─────────────────────────────────────────────
  # Lifecycle API — exposed so orchestrator (or tests) can drive events
  # ─────────────────────────────────────────────

  @property
  def lifecycle(self) -> LifecycleManager:
    return self._lifecycle

  # ─────────────────────────────────────────────
  # Expiry sweeper — call start_expiry_loop() once at startup
  # ─────────────────────────────────────────────

  def start_expiry_loop(self, ttl_seconds: int = 60, interval_seconds: int = 30) -> None:
    """
    Periodically expire 'pending' events that no orchestrator picked up.
    Safe to call once; subsequent calls are no-ops.
    """
    if self._expiry_task is not None and not self._expiry_task.done():
      return
    self._expiry_task = asyncio.create_task(
      self._expiry_loop(ttl_seconds, interval_seconds)
    )

  async def stop_expiry_loop(self) -> None:
    if self._expiry_task is None:
      return
    self._expiry_task.cancel()
    try:
      await self._expiry_task
    except (asyncio.CancelledError, Exception):
      pass
    self._expiry_task = None

  async def _expiry_loop(self, ttl_seconds: int, interval_seconds: int) -> None:
    while True:
      try:
        await asyncio.sleep(interval_seconds)
        await self._lifecycle.expire_stale(ttl_seconds)
      except asyncio.CancelledError:
        raise
      except Exception as e:
        logger.error(f"Expiry sweep failed: {e}")

  # ─────────────────────────────────────────────
  # Internal
  # ─────────────────────────────────────────────

  async def _dedup_and_persist(self, event: Event) -> bool:
    """
    Returns True iff a new row was inserted (i.e. the event should be
    dispatched). False means deduper suppressed it.
    """
    decision = await self._deduper.check(event)
    if decision.decision == DedupDecision.SUPPRESS:
      return False
    await self._repo.insert(event)
    return True
