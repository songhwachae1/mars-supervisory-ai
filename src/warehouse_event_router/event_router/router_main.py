"""
Entrypoint: `event_router` console script.

Boots:
  - asyncpg pool                 (router's own DB ops + nodes' DB ops)
  - WorkflowRuntime              (LangGraph checkpointer + compiled graphs)
  - EventRouter                  (claim → route → launch loop)

Then waits for SIGINT/SIGTERM and shuts everything down in reverse.
"""

import asyncio
import logging
import signal
from typing import Optional

import asyncpg

from event_router import config
from event_router.router import EventRouter

logger = logging.getLogger(__name__)


async def _amain() -> None:
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
  )

  pool: Optional[asyncpg.Pool] = None
  runtime = None
  router: Optional[EventRouter] = None

  try:
    pool = await asyncpg.create_pool(
      config.DB_DSN,
      min_size=config.DB_POOL_MIN,
      max_size=config.DB_POOL_MAX,
    )

    # Late import: keeps `event_router` itself free of a hard
    # dependency on langgraph for use cases (e.g. tests) that don't
    # need the workflow layer.
    from workflows import WorkflowRuntime
    runtime = WorkflowRuntime(pool, config.DB_DSN)
    await runtime.start()

    router = EventRouter(pool, runtime)

    # Wire OS signals to a clean stop.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
      try:
        loop.add_signal_handler(sig, router.stop)
      except NotImplementedError:
        pass

    await router.run()

  finally:
    if runtime is not None:
      try:
        await runtime.stop()
      except Exception as e:
        logger.error(f"Runtime stop error: {e}")
    if pool is not None:
      await pool.close()


def main() -> None:
  try:
    asyncio.run(_amain())
  except KeyboardInterrupt:
    pass


if __name__ == "__main__":
  main()
