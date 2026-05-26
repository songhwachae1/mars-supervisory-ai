"""
WorkflowRuntime.

Owns the compiled-graph cache and the checkpointer lifecycle. The
launcher holds one instance, constructed at boot.

Responsibilities:
  - start the AsyncPostgresSaver and wire it into every compiled graph
  - compile each registered workflow exactly once, on first use
  - expose `invoke(name, state, workflow_id)` for the launcher
  - shut the checkpointer down cleanly

Lazy compile: each graph is built and compiled the first time it's
requested. This keeps boot fast even if the registry grows, and it
means a buggy graph definition only breaks the one route, not the
whole router.
"""

import logging
from typing import Dict, Optional

import asyncpg
from langgraph.graph.state import CompiledStateGraph

from workflows.checkpointer import CheckpointerHandle
from workflows.registry import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


class UnknownWorkflow(Exception):
  pass


class WorkflowRuntime:

  def __init__(self, pool: asyncpg.Pool, dsn: str):
    """
    pool : asyncpg pool used by graph nodes for application DB writes.
    dsn  : connection string for the LangGraph AsyncPostgresSaver
           (uses psycopg3 internally; separate from `pool`).
    """
    self._pool = pool
    self._checkpointer = CheckpointerHandle(dsn)
    self._compiled: Dict[str, CompiledStateGraph] = {}

  # ─────────────────────────────────────────────
  # Lifecycle
  # ─────────────────────────────────────────────

  async def start(self) -> None:
    await self._checkpointer.start()
    logger.info(f"WorkflowRuntime started; {len(WORKFLOW_REGISTRY)} workflows registered")

  async def stop(self) -> None:
    await self._checkpointer.stop()
    self._compiled.clear()

  # ─────────────────────────────────────────────
  # Public API
  # ─────────────────────────────────────────────

  def has(self, name: str) -> bool:
    return name in WORKFLOW_REGISTRY

  async def invoke(self, name: str, initial_state: dict, workflow_id: str) -> None:
    """
    Invoke the named workflow. Raises UnknownWorkflow if the name
    isn't registered.

    LangGraph's checkpointer keys on `thread_id`, which we set to
    `workflow_id` — this also makes the checkpoint trail joinable to
    workflow_execution.
    """
    graph = self._get_or_compile(name)
    config = {"configurable": {"thread_id": workflow_id}}
    await graph.ainvoke(initial_state, config)

  # ─────────────────────────────────────────────
  # Internal
  # ─────────────────────────────────────────────

  def _get_or_compile(self, name: str) -> CompiledStateGraph:
    if name in self._compiled:
      return self._compiled[name]

    factory = WORKFLOW_REGISTRY.get(name)
    if factory is None:
      raise UnknownWorkflow(name)

    builder = factory(self._pool)
    compiled = builder.compile(checkpointer=self._checkpointer.saver)
    self._compiled[name] = compiled
    logger.info(f"Compiled workflow graph: {name}")
    return compiled
