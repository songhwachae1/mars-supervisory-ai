"""
EventRouter — the main loop.

Two wakeup sources, OR'd together via an asyncio.Event:

  1. Postgres NOTIFY on the 'robot_events_new' channel
     The event_system's dispatcher fires this when it inserts an event.
     The router's LISTEN task sets the wakeup event.

  2. Periodic poll (config.POLL_INTERVAL_S)
     Safety net for missed notifications: router restarts, dropped
     connections, etc. Also covers retries of events that errored
     during routing.

Each wakeup runs `_drain()`, which loops claim → route → launch until
no more events are available, then returns to waiting.

Determinism:
  - Workflow selection is a dict lookup, not a search.
  - Severity-then-time ordering at the claim level gives a stable order.
  - No event is "skipped" silently; unmapped / informational events get
    terminal status with a clear log line.

This file is deliberately plumbing-only. Anything resembling a policy
decision belongs in workflow_map.py.
"""

import asyncio
import logging
from typing import Optional

import asyncpg

from event_router import config
from event_router.claimer import EventClaimer
from event_router.input_builder import WorkflowInputBuilder
from event_router.launcher import WorkflowLauncher
from event_router.models import ClaimedEvent
from event_router.selector import WorkflowSelector
from event_router.tracker import ExecutionTracker

logger = logging.getLogger(__name__)


class EventRouter:

  def __init__(self, pool: asyncpg.Pool, runtime):
    """
    runtime : workflows.WorkflowRuntime
              Owns the LangGraph checkpointer and the compiled graphs.
              Must already be started before run() is awaited.
    """
    self._pool = pool

    self._claimer   = EventClaimer(pool)
    self._selector  = WorkflowSelector()
    self._builder   = WorkflowInputBuilder(pool)
    self._launcher  = WorkflowLauncher(pool, runtime)
    self._tracker   = ExecutionTracker(pool)

    self._wakeup = asyncio.Event()
    self._stop   = asyncio.Event()

    # Dedicated connection for LISTEN (one connection per LISTENing
    # subscriber is the standard asyncpg pattern).
    self._listen_conn: Optional[asyncpg.Connection] = None

  # ─────────────────────────────────────────────
  # Public lifecycle
  # ─────────────────────────────────────────────

  async def run(self) -> None:
    """Block until stop() is called."""
    await self._start_listener()

    poll_task    = asyncio.create_task(self._poll_loop(),    name="router_poll")
    reconcile_t  = asyncio.create_task(self._reconcile_loop(), name="router_reconcile")
    process_task = asyncio.create_task(self._process_loop(), name="router_process")

    logger.info("EventRouter running")

    try:
      await self._stop.wait()
    finally:
      for t in (poll_task, reconcile_t, process_task):
        t.cancel()
      for t in (poll_task, reconcile_t, process_task):
        try:
          await t
        except (asyncio.CancelledError, Exception):
          pass
      await self._stop_listener()
      logger.info("EventRouter stopped")

  def stop(self) -> None:
    self._stop.set()
    self._wakeup.set()  # unblock the process loop

  # ─────────────────────────────────────────────
  # LISTEN / NOTIFY
  # ─────────────────────────────────────────────

  async def _start_listener(self) -> None:
    self._listen_conn = await self._pool.acquire()
    await self._listen_conn.add_listener(config.NOTIFY_CHANNEL, self._on_notify)
    logger.info(f"Listening for NOTIFY on '{config.NOTIFY_CHANNEL}'")

  async def _stop_listener(self) -> None:
    if self._listen_conn is None:
      return
    try:
      await self._listen_conn.remove_listener(config.NOTIFY_CHANNEL, self._on_notify)
    except Exception:
      pass
    await self._pool.release(self._listen_conn)
    self._listen_conn = None

  def _on_notify(self, conn, pid, channel, payload) -> None:
    # asyncpg invokes this on the event loop; flipping an asyncio.Event
    # is the safe way to hand off to the process loop.
    self._wakeup.set()

  # ─────────────────────────────────────────────
  # Background loops
  # ─────────────────────────────────────────────

  async def _poll_loop(self) -> None:
    """Safety-net poll. Sets the wakeup flag on a fixed interval."""
    while not self._stop.is_set():
      try:
        await asyncio.sleep(config.POLL_INTERVAL_S)
        self._wakeup.set()
      except asyncio.CancelledError:
        raise

  async def _reconcile_loop(self) -> None:
    """Periodic tracker sweep — picks up workflows that finished without
    a direct callback path back to the router."""
    while not self._stop.is_set():
      try:
        await asyncio.sleep(config.POLL_INTERVAL_S * 2)
        await self._tracker.reconcile()
      except asyncio.CancelledError:
        raise
      except Exception as e:
        logger.error(f"Reconcile loop error: {e}")

  async def _process_loop(self) -> None:
    """Main consumer. Drains claimed events whenever woken up."""
    while not self._stop.is_set():
      await self._wakeup.wait()
      self._wakeup.clear()
      if self._stop.is_set():
        break
      try:
        await self._drain()
      except Exception as e:
        logger.error(f"Process loop error: {e}")

  # ─────────────────────────────────────────────
  # Drain a wakeup
  # ─────────────────────────────────────────────

  async def _drain(self) -> None:
    """Keep claiming until no events come back."""
    while True:
      events = await self._claimer.claim_batch(config.CLAIM_BATCH_SIZE)
      if not events:
        return
      for event in events:
        await self._route_one(event)

  async def _route_one(self, event: ClaimedEvent) -> None:
    decision, workflow_name = self._selector.select(event.event_type)

    if decision == "informational":
      logger.info(
        f"Event {event.event_id} ({event.event_type}) is informational; "
        f"closing without workflow"
      )
      await self._tracker.mark_completed(event.event_id)
      return

    if decision == "unmapped":
      logger.warning(
        f"Event {event.event_id} ({event.event_type}) has no workflow mapping; "
        f"closing as completed"
      )
      await self._tracker.mark_completed(event.event_id)
      return

    # decision == "launch"
    workflow_input = await self._builder.build(event)
    workflow_id    = await self._launcher.launch(workflow_name, event, workflow_input)

    if workflow_id is None:
      # Launch failed at DB write — leave event in_progress for the
      # expiry sweeper to expire. Do NOT mark failed here, since the
      # workflow never actually started; the failure is at the router
      # layer, not the workflow's.
      logger.error(
        f"Event {event.event_id} routing aborted (launcher returned None)"
      )
