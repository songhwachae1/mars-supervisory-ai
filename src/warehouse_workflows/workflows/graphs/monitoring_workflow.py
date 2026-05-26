"""
monitoring_workflow

Triggered by:  health_degraded

Plan:
  1. record_observation — capture the degraded state in anomaly_records
                          with a 'warning' severity. No motion change,
                          no agent_command — the robot continues its
                          current task under observation.
  2. finalize           — close workflow_execution.

Intentionally minimal. health_degraded is the soft signal; if it
becomes critical, diagnostic_workflow takes over.
"""

import logging

import asyncpg
from langgraph.graph import StateGraph, END

from workflows import db, terminal
from workflows.graphs._shared import decision, audit_checkpoint
from workflows.state import WorkflowState

logger = logging.getLogger(__name__)


def build_graph(pool: asyncpg.Pool) -> StateGraph:

  async def record_observation(state: WorkflowState) -> dict:
    event = state["event"]
    anomaly_id = await db.insert_anomaly(
      pool,
      robot_id=event["robot_id"],
      anomaly_type="health_degraded",
      severity="warning",
      detected_by="monitoring_workflow",
      related_event_id=event["event_id"],
      description=(
        f"{event['robot_id']} health degraded; continuing under observation."
      ),
      state_snapshot={
        "robot_state":   state.get("robot_state"),
        "event_payload": event.get("payload"),
      },
    )
    await audit_checkpoint(pool, state["workflow_id"], "record_observation", {"anomaly_id": anomaly_id})
    return {
      "anomaly_id": anomaly_id,
      "decisions":  [decision("record_observation", anomaly_id=anomaly_id)],
    }

  async def finalize(state: WorkflowState) -> dict:
    await terminal.mark_workflow_completed(pool, state["workflow_id"], "finalize")
    return {"status": "completed"}

  graph = StateGraph(WorkflowState)
  graph.add_node("record_observation", record_observation)
  graph.add_node("finalize",           finalize)

  graph.set_entry_point("record_observation")
  graph.add_edge("record_observation", "finalize")
  graph.add_edge("finalize", END)
  return graph
