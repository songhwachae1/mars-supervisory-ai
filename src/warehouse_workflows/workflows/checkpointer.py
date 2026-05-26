"""
LangGraph checkpointer setup.

Uses langgraph-checkpoint-postgres' AsyncPostgresSaver, which writes
its own internal tables (checkpoints, checkpoint_blobs, checkpoint_writes)
on first run. Those tables are LangGraph-managed; do not edit by hand.

The project's existing `workflow_checkpoints` table is a separate,
human-readable audit log (see graphs/_shared.audit_checkpoint). Both
are useful: the LangGraph tables let workflows resume; the audit log
lets a human review what each node decided without parsing pickled
state.

This module owns the checkpointer lifecycle (start/stop) so the
runtime can construct it once at boot and reuse it across all graphs.
"""

import logging
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

logger = logging.getLogger(__name__)


class CheckpointerHandle:
  """
  Lifecycle wrapper around AsyncPostgresSaver.

  AsyncPostgresSaver.from_conn_string is an async context manager.
  This handle holds the underlying context so the runtime can enter
  it at startup and exit it at shutdown without `async with` syntax
  in the call site.
  """

  def __init__(self, dsn: str):
    self._dsn = dsn
    self._ctx = None
    self._saver: Optional[AsyncPostgresSaver] = None

  async def start(self) -> AsyncPostgresSaver:
    self._ctx = AsyncPostgresSaver.from_conn_string(self._dsn)
    self._saver = await self._ctx.__aenter__()
    await self._saver.setup()
    logger.info("LangGraph AsyncPostgresSaver initialized")
    return self._saver

  async def stop(self) -> None:
    if self._ctx is None:
      return
    try:
      await self._ctx.__aexit__(None, None, None)
    except Exception as e:
      logger.error(f"Checkpointer shutdown error: {e}")
    finally:
      self._ctx = None
      self._saver = None

  @property
  def saver(self) -> Optional[AsyncPostgresSaver]:
    return self._saver
