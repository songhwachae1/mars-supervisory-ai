"""
WorkflowLauncher.

Takes a (workflow_name, WorkflowInput) pair and starts the workflow.

What the launcher OWNS:

  - generating the workflow_id (UUID)
  - inserting the workflow_execution row (so the workflow appears in
    the blackboard the instant it's launched, not after it finishes)
  - linking the event to the workflow_id via robot_events.workflow_id
  - calling into WorkflowRuntime to compile + invoke the graph
  - converting unknown / unimplemented workflows to a clean failed
    workflow_execution row instead of crashing the router

What the launcher does NOT own:

  - graph definitions    → workflows/graphs/*
  - the registry         → workflows/registry.py
  - checkpointer wiring  → workflows/runtime.py + workflows/checkpointer.py
  - per-node behavior    → the graphs themselves

Concurrency model: launch() returns the moment LangGraph invocation has
been scheduled. The actual graph runs in a background task. This keeps
the router's claim loop snappy even if a workflow takes seconds.
"""

import asyncio
import logging
from typing import Optional
from uuid import UUID, uuid4

import asyncpg

from event_router import queries
from event_router.models import ClaimedEvent, WorkflowInput

logger = logging.getLogger(__name__)


class WorkflowLauncher:

  def __init__(self, pool: asyncpg.Pool, runtime):
    """
    runtime : workflows.WorkflowRuntime
              Constructed by the entrypoint and started before the
              router begins claiming events. The launcher does not
              own the runtime's lifecycle.
    """
    self._pool = pool
    self._runtime = runtime

  async def launch(
    self,
    workflow_name: str,
    event: ClaimedEvent,
    workflow_input: WorkflowInput,
  ) -> Optional[UUID]:
    """
    Persist the workflow_execution row, link it to the event, and
    schedule the graph invocation.

    Returns the assigned workflow_id, or None if the DB write step
    failed (in which case the event is left in_progress and the
    expiry sweeper will eventually expire it).
    """
    workflow_id = uuid4()

    try:
      async with self._pool.acquire() as conn:
        async with conn.transaction():
          await conn.execute(
            queries.INSERT_WORKFLOW_EXECUTION,
            str(workflow_id),
            workflow_name,
          )
          await conn.execute(
            queries.LINK_WORKFLOW,
            str(workflow_id),
            event.event_id,
          )
    except Exception as e:
      logger.error(
        f"Launch failed (DB write) workflow_name={workflow_name} "
        f"event_id={event.event_id}: {e}"
      )
      return None

    # If the workflow isn't registered, mark it failed immediately
    # rather than throwing into a background task that nobody awaits.
    if not self._runtime.has(workflow_name):
      logger.warning(
        f"No registered graph for '{workflow_name}'; "
        f"marking workflow_id={workflow_id} as failed"
      )
      await self._mark_failed_unknown(workflow_id)
      return workflow_id

    # Build the initial LangGraph state and schedule the invocation.
    initial_state = {
      **workflow_input.to_dict(),
      "workflow_id":     str(workflow_id),
      "decisions":       [],
      "commands_issued": [],
    }
    asyncio.create_task(
      self._invoke_safely(workflow_name, initial_state, str(workflow_id)),
      name=f"workflow:{workflow_name}:{workflow_id}",
    )

    logger.info(
      f"Launched workflow_id={workflow_id} type={workflow_name} "
      f"for event_id={event.event_id} robot={event.robot_id}"
    )
    return workflow_id

  # ─────────────────────────────────────────────
  # Internal
  # ─────────────────────────────────────────────

  async def _invoke_safely(self, workflow_name: str, initial_state: dict, workflow_id: str) -> None:
    """
    Run the graph in a try/except so an uncaught error in a node
    can't take down the router's event loop. On failure, mark the
    workflow_execution row failed; the ExecutionTracker will then
    reconcile the linked robot_events row.
    """
    try:
      await self._runtime.invoke(workflow_name, initial_state, workflow_id)
    except Exception as e:
      logger.error(
        f"Workflow invocation crashed: workflow_id={workflow_id} "
        f"type={workflow_name}: {e!r}"
      )
      await self._mark_failed_crashed(workflow_id)

  async def _mark_failed_unknown(self, workflow_id: UUID) -> None:
    await self._exec_workflow_status(
      workflow_id, status="failed", current_node="unknown_workflow"
    )

  async def _mark_failed_crashed(self, workflow_id: str) -> None:
    await self._exec_workflow_status(
      workflow_id, status="failed", current_node="crashed"
    )

  async def _exec_workflow_status(self, workflow_id, status: str, current_node: str) -> None:
    sql = """
      UPDATE workflow_execution
      SET status        = $2,
          current_node  = $3,
          updated_at    = NOW()
      WHERE workflow_id = $1::uuid
    """
    try:
      async with self._pool.acquire() as conn:
        await conn.execute(sql, str(workflow_id), status, current_node)
    except Exception as e:
      logger.error(f"Failed to update workflow_execution {workflow_id}: {e}")
