"""
diagnostic_workflow

Triggered by:  robot_error, health_critical

Plan:
  1. record_anomaly     — capture the event + current state in
                          anomaly_records so the Anomaly Detection
                          Agent (or a human) can review.
  2. pause_robot        — write a high-priority 'pause_robot' command
                          so the executor halts motion.
  3. request_intervention — second anomaly_records row tagged
                          'needs_human' so an operator dashboard can
                          surface it.
  4. finalize           — close workflow_execution.

This is a *safety* workflow: it never re-routes or recovers the
robot; it stops the robot and tells someone. Recovery is recovery_workflow's
job.
"""

import logging

import asyncpg
from langgraph.graph import StateGraph, END

from workflows import db, terminal
from workflows.graphs._shared import decision, audit_checkpoint
from workflows.state import WorkflowState

logger = logging.getLogger(__name__)


def build_graph(pool: asyncpg.Pool) -> StateGraph:

  async def record_anomaly(state: WorkflowState) -> dict:
    event = state["event"]
    anomaly_id = await db.insert_anomaly(
      pool,
      robot_id=event["robot_id"],
      anomaly_type=event["event_type"],
      severity=event.get("severity", "critical"),
      detected_by="diagnostic_workflow",
      related_event_id=event["event_id"],
      description=f"{event['event_type']} reported by {event.get('source_component')}",
      state_snapshot={
        "robot_state":    state.get("robot_state"),
        "active_mission": state.get("active_mission"),
        "event_payload":  event.get("payload"),
      },
    )
    await audit_checkpoint(pool, state["workflow_id"], "record_anomaly", {"anomaly_id": anomaly_id})
    return {
      "anomaly_id": anomaly_id,
      "decisions": [decision("record_anomaly", anomaly_id=anomaly_id)],
    }

  async def pause_robot(state: WorkflowState) -> dict:
    command_id = await db.insert_agent_command(
      pool,
      robot_id=state["event"]["robot_id"],
      source_agent="diagnostic_workflow",
      command_type="pause_robot",
      payload={"reason": state["event"]["event_type"]},
      priority=20,  # safety > everything else
    )
    await audit_checkpoint(pool, state["workflow_id"], "pause_robot", {"command_id": command_id})
    return {
      "commands_issued": [command_id],
      "decisions": [decision("pause_robot", command_id=command_id)],
    }

  async def request_intervention(state: WorkflowState) -> dict:
    intervention_id = await db.insert_anomaly(
      pool,
      robot_id=state["event"]["robot_id"],
      anomaly_type="needs_human_intervention",
      severity="critical",
      detected_by="diagnostic_workflow",
      related_event_id=state["event"]["event_id"],
      description=(
        f"Diagnostic workflow halted {state['event']['robot_id']} due to "
        f"{state['event']['event_type']}. Manual review required."
      ),
      state_snapshot={"linked_anomaly_id": state.get("anomaly_id")},
    )
    await audit_checkpoint(pool, state["workflow_id"], "request_intervention", {"intervention_id": intervention_id})
    return {"decisions": [decision("request_intervention", intervention_id=intervention_id)]}

  async def finalize(state: WorkflowState) -> dict:
    await terminal.mark_workflow_completed(pool, state["workflow_id"], "finalize")
    return {"status": "completed"}

  graph = StateGraph(WorkflowState)
  graph.add_node("record_anomaly",        record_anomaly)
  graph.add_node("pause_robot",           pause_robot)
  graph.add_node("request_intervention",  request_intervention)
  graph.add_node("finalize",              finalize)

  graph.set_entry_point("record_anomaly")
  graph.add_edge("record_anomaly",       "pause_robot")
  graph.add_edge("pause_robot",          "request_intervention")
  graph.add_edge("request_intervention", "finalize")
  graph.add_edge("finalize", END)
  return graph
