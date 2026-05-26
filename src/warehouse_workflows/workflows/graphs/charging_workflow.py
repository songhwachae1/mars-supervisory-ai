"""
charging_workflow

Triggered by:  battery_low  (non-urgent companion to emergency_charging_workflow)

Plan (deterministic, no LLM):
  1. check_eta_to_completion — can the robot finish its current task and
                               still reach the nearest charger with a
                               safety margin to spare?
  2. finish_then_charge      — if yes, schedule a low-priority navigate_to
                               the charger so it runs after current work.
  3. interrupt_and_charge    — if no, pause mission and issue a
                               high-priority navigate_to the charger.
  4. finalize                — mark workflow_execution completed/failed.
"""

import logging
import math

import asyncpg
from langgraph.graph import StateGraph

from workflows import db, terminal
from workflows.graphs._shared import decision, audit_checkpoint
from workflows.state import WorkflowState

logger = logging.getLogger(__name__)


# Energy-budget constants.
# These are coarse first-cut values; tune from telemetry once available.
BATTERY_PCT_PER_METER = 0.05   # ~20 m per 1% battery
SAFETY_MARGIN_PCT     = 10.0   # reserve to absorb estimation error


def build_graph(pool: asyncpg.Pool) -> StateGraph:

  async def check_eta_to_completion(state: WorkflowState) -> dict:
    """
    Decide whether the robot can finish its current task and still reach
    a charger safely. Writes `can_finish_task` (bool) into state, plus
    `selected_charger` so a downstream navigate node can reuse it.
    """
    robot_state = state.get("robot_state") or {}
    mission     = state.get("active_mission")

    battery_now = robot_state.get("battery_pct")
    rx          = robot_state.get("x")
    ry          = robot_state.get("y")

    # Missing telemetry → cannot reason about the budget; fail safe.
    if battery_now is None or rx is None or ry is None:
      await audit_checkpoint(
        pool, state["workflow_id"], "check_eta_to_completion",
        {"reason": "missing_telemetry"},
      )
      return {
        "can_finish_task": False,
        "decisions": [decision("check_eta_to_completion", reason="missing_telemetry")],
      }

    # No active mission → robot is idle; "finishing the task" is trivial.
    if not mission or not mission.get("destination_location"):
      charger = await db.find_nearest_charger(pool, rx, ry)
      await audit_checkpoint(
        pool, state["workflow_id"], "check_eta_to_completion",
        {"reason": "no_active_mission", "charger": charger},
      )
      return {
        "can_finish_task": True,
        "selected_charger": charger,
        "decisions": [decision(
          "check_eta_to_completion",
          reason="no_active_mission",
          charger_shelf=charger["shelf_id"] if charger else None,
        )],
      }

    # Resolve mission destination → (x, y).
    # NOTE: this approximates "task endpoint" as "mission endpoint" — fine
    # as an over-estimate for v1; tighten via tasks.payload later.
    dest_shelf = mission["destination_location"]
    dest = await db.find_location(pool, dest_shelf)
    if dest is None:
      await audit_checkpoint(
        pool, state["workflow_id"], "check_eta_to_completion",
        {"reason": "unknown_destination", "shelf_id": dest_shelf},
      )
      return {
        "can_finish_task": False,
        "decisions": [decision(
          "check_eta_to_completion",
          reason="unknown_destination",
          shelf_id=dest_shelf,
        )],
      }

    # Nearest charger is computed from the task endpoint, not from the
    # robot's current pose — that's the trip the robot will actually take.
    charger = await db.find_nearest_charger(pool, dest["x"], dest["y"])
    if charger is None:
      await audit_checkpoint(
        pool, state["workflow_id"], "check_eta_to_completion",
        {"reason": "no_charger_available"},
      )
      return {
        "can_finish_task": False,
        "error": "no_charger_available",
        "decisions": [decision("check_eta_to_completion", reason="no_charger_available")],
      }

    dist_finish  = math.hypot(dest["x"] - rx,        dest["y"] - ry)
    dist_charger = math.hypot(charger["x"] - dest["x"], charger["y"] - dest["y"])
    required     = (dist_finish + dist_charger) * BATTERY_PCT_PER_METER + SAFETY_MARGIN_PCT
    can_finish   = battery_now >= required

    await audit_checkpoint(
      pool, state["workflow_id"], "check_eta_to_completion",
      {
        "battery_now":  battery_now,
        "dist_finish":  dist_finish,
        "dist_charger": dist_charger,
        "required":     required,
        "can_finish":   can_finish,
      },
    )
    return {
      "selected_charger": charger,
      "can_finish_task":  can_finish,
      "decisions": [decision(
        "check_eta_to_completion",
        battery_now  = battery_now,
        dist_finish  = round(dist_finish,  2),
        dist_charger = round(dist_charger, 2),
        required     = round(required,     2),
        can_finish   = can_finish,
      )],
    }

  def route_charge_decision(state: WorkflowState):
    # If check_eta_to_completion couldn't pick a charger at all, skip
    # straight to finalize so it's marked failed without a no-op detour
    # through interrupt_and_charge.
    if state.get("error"):
      return "finalize"
    if state.get("can_finish_task"):
      return "finish_then_charge"
    return "interrupt_and_charge"

  async def finish_then_charge(state: WorkflowState) -> dict:
    charger = state.get("selected_charger")
    if charger is None:
      return {"decisions": [decision("finish_then_charge", action="skipped_no_charger")]}

    command_id = await db.insert_agent_command(
      pool,
      robot_id=state["event"]["robot_id"],
      source_agent="charging_workflow",
      command_type="navigate_to",
      payload={
        "destination_shelf_id": charger["shelf_id"],
        "x": charger["x"],
        "y": charger["y"],
        "reason": "battery_low but enough to finish the task",
      },
      priority=3,
    )
    await audit_checkpoint(pool, state["workflow_id"], "finish_then_charge", {"command_id": command_id})
    return {
      "commands_issued": [command_id],
      "decisions": [decision("finish_then_charge", command_id=command_id, target=charger["shelf_id"])],
    }

  async def interrupt_and_charge(state: WorkflowState) -> dict:
    charger = state.get("selected_charger")
    if charger is None:
      return {"decisions": [decision("interrupt_and_charge", action="skipped_no_charger")]}

    mission = state.get("active_mission")
    if mission is None:
      return {"decisions": [decision("interrupt_and_charge", action="skipped_no_active_mission")]}

    mid = mission["mission_id"]
    if hasattr(mid, "hex"):  # UUID → str
      mid = str(mid)

    await db.update_mission_status(pool, mid, "paused")
    command_id = await db.insert_agent_command(
      pool,
      robot_id=state["event"]["robot_id"],
      source_agent="charging_workflow",
      command_type="navigate_to",
      payload={
        "destination_shelf_id": charger["shelf_id"],
        "x": charger["x"],
        "y": charger["y"],
        "reason": "battery_low but not enough to finish",
      },
      priority=10,
    )

    await audit_checkpoint(pool, state["workflow_id"], "interrupt_and_charge", {"command_id": command_id})
    return {
      "commands_issued": [command_id],
      "paused_mission_id": mid,
      "decisions": [decision("interrupt_and_charge", command_id=command_id, target=charger["shelf_id"])],
    }

  async def finalize(state: WorkflowState) -> dict:
    if state.get("error"):
      await terminal.mark_workflow_failed(pool, state["workflow_id"], "finalize")
      logger.error(
        f"charging_workflow failed: workflow_id={state['workflow_id']} "
        f"error={state['error']}"
      )
      return {"status": "failed"}
    await terminal.mark_workflow_completed(pool, state["workflow_id"], "finalize")
    return {"status": "completed"}

  graph = StateGraph(WorkflowState)
  graph.add_node("check_eta_to_completion", check_eta_to_completion)
  graph.add_node("finish_then_charge", finish_then_charge)
  graph.add_node("interrupt_and_charge", interrupt_and_charge)
  graph.add_node("finalize", finalize)

  graph.set_entry_point("check_eta_to_completion")
  graph.add_conditional_edges("check_eta_to_completion", route_charge_decision, {
    "finish_then_charge":   "finish_then_charge",
    "interrupt_and_charge": "interrupt_and_charge",
    "finalize":             "finalize",
  })
  graph.add_edge("finish_then_charge", "finalize")
  graph.add_edge("interrupt_and_charge", "finalize")
  graph.add_edge("finalize", END)
  return graph
