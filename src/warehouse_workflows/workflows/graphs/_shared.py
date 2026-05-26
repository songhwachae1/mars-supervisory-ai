"""
Shared helpers for workflow graphs.

Two utilities live here:

  - audit_checkpoint  : writes a human-readable row to workflow_checkpoints
                        whenever a node wants to record its decision.
                        This is independent of LangGraph's internal
                        checkpointing.

  - decision          : standard shape for entries in state["decisions"].
                        Keeps the audit log uniform across workflows.
"""

import json
import logging
from datetime import datetime
from typing import Optional

import asyncpg

from workflows import queries

logger = logging.getLogger(__name__)


def decision(node: str, **fields) -> dict:
  """
  Build a uniform audit-log entry. Always includes `node` and `at`.
  Caller adds any per-node data via kwargs.
  """
  out = {"node": node, "at": datetime.utcnow().isoformat()}
  out.update(fields)
  return out


async def audit_checkpoint(
  pool: asyncpg.Pool,
  workflow_id: str,
  node_name: str,
  state_snapshot: dict,
) -> None:
  """
  Best-effort audit log. Any failure is logged but never raised,
  since the workflow's correctness must not depend on logging.
  """
  try:
    async with pool.acquire() as conn:
      await conn.execute(
        queries.INSERT_AUDIT_CHECKPOINT,
        workflow_id,
        node_name,
        json.dumps(state_snapshot, default=str),
      )
  except Exception as e:
    logger.error(f"audit_checkpoint failed for workflow={workflow_id} node={node_name}: {e}")
