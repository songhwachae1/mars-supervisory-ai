"""
Terminal helpers — mark workflow_execution and the linked robot_events row.

Every graph ends with a `finalize` node that calls one of these
helpers. We update workflow_execution first; the ExecutionTracker in
the router then reconciles the event status on its next sweep.

For workflows that want to close the event eagerly (without waiting
for the tracker), `mark_event_terminal` is available — but most
workflows don't need it, since the tracker handles it asynchronously.
"""

import logging
from typing import Optional

import asyncpg

from workflows import queries

logger = logging.getLogger(__name__)


async def mark_workflow_completed(
  pool: asyncpg.Pool,
  workflow_id: str,
  terminal_node: str = "finalize",
) -> None:
  async with pool.acquire() as conn:
    await conn.execute(queries.MARK_WORKFLOW_COMPLETED, workflow_id, terminal_node)


async def mark_workflow_failed(
  pool: asyncpg.Pool,
  workflow_id: str,
  terminal_node: str = "finalize",
) -> None:
  async with pool.acquire() as conn:
    await conn.execute(queries.MARK_WORKFLOW_FAILED, workflow_id, terminal_node)


async def update_current_node(
  pool: asyncpg.Pool,
  workflow_id: str,
  node_name: str,
) -> None:
  async with pool.acquire() as conn:
    await conn.execute(queries.UPDATE_WORKFLOW_CURRENT_NODE, workflow_id, node_name)
