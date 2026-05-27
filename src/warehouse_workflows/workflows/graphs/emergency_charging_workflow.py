"""
emergency_charging_workflow

Triggered by:  battery_critical

Plan (deterministic, no LLM):
  1. select_charger     — find the nearest warehouse_locations row with
                          location_type='charger'.
  2. pause_mission      — if the robot has an active mission, set its
                          status to 'paused' so the scheduler doesn't
                          treat it as in-flight.
  3. issue_navigate     — write an agent_command of type 'navigate_to'
                          targeting the selected charger, at high
                          priority. ROS executors pick this up.
  4. finalize           — mark workflow_execution as completed (or
                          failed, if step 1 found no charger).

This workflow does NOT command motion directly. It writes an
agent_command and lets the executor layer drive the robot.
"""

import logging

import asyncpg
from langgraph.graph import StateGraph, END

from workflows import db, terminal, tools
from workflows.graphs._shared import decision, audit_checkpoint
from workflows.state import WorkflowState

logger = logging.getLogger(__name__)


def build_graph(pool: asyncpg.Pool) -> StateGraph:
  """Construct the StateGraph. Caller compiles with a checkpointer."""

  async def select_charger(state: WorkflowState) -> dict:
    robot_state = state.get("robot_state") or {}
    charger = await db.find_nearest_charger(
      pool, robot_state.get("x"), robot_state.get("y")
    )
    await audit_checkpoint(pool, state["workflow_id"], "select_charger", {"charger": charger})
    if charger is None:
      return {
        "selected_charger": None,
        "error": "no_charger_available",
        "decisions": [decision("select_charger", found=False)],
      }
    return {
      "selected_charger": charger,
      "decisions": [decision("select_charger", shelf_id=charger["shelf_id"], dist_sq=charger.get("dist_sq"))],
    }

  async def pause_mission(state: WorkflowState) -> dict:
    # Even if select_charger failed, pausing the mission is still safe.
    mission = state.get("active_mission")
    if mission is None:
      return {"decisions": [decision("pause_mission", action="skipped_no_active_mission")]}

    mid = mission["mission_id"]
    if hasattr(mid, "hex"):  # UUID → str
      mid = str(mid)

    receipt = await tools.pause_mission(pool, mission_id=mid, reason="battery_critical")
    await audit_checkpoint(pool, state["workflow_id"], "pause_mission", receipt.to_dict())
    return {
      "paused_mission_id": mid,
      "decisions": [decision("pause_mission", **receipt.to_dict())],
    }

  async def issue_navigate(state: WorkflowState) -> dict:
    charger = state.get("selected_charger")
    if charger is None:
      return {"decisions": [decision("issue_navigate", action="skipped_no_charger")]}

    receipt = await tools.navigate_to(
      pool,
      robot_id=state["event"]["robot_id"],
      destination_shelf_id=charger["shelf_id"],
      reason="battery_critical",
      urgency="critical",
      issued_by="emergency_charging_workflow",
    )
    await audit_checkpoint(pool, state["workflow_id"], "issue_navigate", receipt.to_dict())
    return {
      "commands_issued": [receipt.command_id] if receipt.command_id else [],
      "decisions": [decision("issue_navigate", **receipt.to_dict())],
    }

  async def finalize(state: WorkflowState) -> dict:
    if state.get("error"):
      await terminal.mark_workflow_failed(pool, state["workflow_id"], "finalize")
      logger.error(
        f"emergency_charging_workflow failed: workflow_id={state['workflow_id']} "
        f"error={state['error']}"
      )
      return {"status": "failed"}
    await terminal.mark_workflow_completed(pool, state["workflow_id"], "finalize")
    return {"status": "completed"}

  graph = StateGraph(WorkflowState)
  graph.add_node("select_charger", select_charger)
  graph.add_node("pause_mission",  pause_mission)
  graph.add_node("issue_navigate", issue_navigate)
  graph.add_node("finalize",       finalize)

  graph.set_entry_point("select_charger")
  graph.add_edge("select_charger", "pause_mission")
  graph.add_edge("pause_mission",  "issue_navigate")
  graph.add_edge("issue_navigate", "finalize")
  graph.add_edge("finalize", END)
  return graph
