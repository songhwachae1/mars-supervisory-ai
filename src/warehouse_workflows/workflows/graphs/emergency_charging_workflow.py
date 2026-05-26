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

from workflows import db, terminal
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

    await db.update_mission_status(pool, mid, "paused")
    await audit_checkpoint(pool, state["workflow_id"], "pause_mission", {"mission_id": mid})
    return {
      "paused_mission_id": mid,
      "decisions": [decision("pause_mission", mission_id=mid)],
    }

  async def issue_navigate(state: WorkflowState) -> dict:
    charger = state.get("selected_charger")
    if charger is None:
      # select_charger already set error; nothing more to do here.
      return {"decisions": [decision("issue_navigate", action="skipped_no_charger")]}

    command_id = await db.insert_agent_command(
      pool,
      robot_id=state["event"]["robot_id"],
      source_agent="emergency_charging_workflow",
      command_type="navigate_to",
      payload={
        "destination_shelf_id": charger["shelf_id"],
        "x": charger["x"],
        "y": charger["y"],
        "reason": "battery_critical",
      },
      priority=10,  # high
    )
    await audit_checkpoint(pool, state["workflow_id"], "issue_navigate", {"command_id": command_id})
    return {
      "commands_issued": [command_id],
      "decisions": [decision("issue_navigate", command_id=command_id, target=charger["shelf_id"])],
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
