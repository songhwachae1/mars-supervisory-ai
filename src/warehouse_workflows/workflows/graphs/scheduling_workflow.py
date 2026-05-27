"""
scheduling_workflow

Triggered by:  robot_idle

Plan:
  1. claim_pending_mission — atomically pick the highest-priority
                             pending mission and assign it to the idle
                             robot. Uses FOR UPDATE SKIP LOCKED so two
                             idle robots can't grab the same mission.
  2. dispatch_first_task   — find the first task of the claimed mission
                             and activate it. Issue an agent_command
                             that kicks off task execution.
  3. finalize              — close workflow_execution.

If no mission is available, the workflow still completes successfully —
"nothing to schedule" is a valid outcome, not a failure.
"""

import logging

import asyncpg
from langgraph.graph import StateGraph, END

from workflows import db, terminal, tools
from workflows.graphs._shared import decision, audit_checkpoint
from workflows.state import WorkflowState

logger = logging.getLogger(__name__)


def build_graph(pool: asyncpg.Pool) -> StateGraph:

  async def claim_pending_mission(state: WorkflowState) -> dict:
    robot_id = state["event"]["robot_id"]
    receipt = await tools.claim_mission(pool, robot_id=robot_id)
    mission = receipt.meta.get("mission")
    await audit_checkpoint(
      pool, state["workflow_id"], "claim_pending_mission",
      {"claimed": mission is not None, "mission": mission},
    )
    if mission is None:
      return {"decisions": [decision("claim_pending_mission", claimed=False)]}
    return {
      "assigned_mission_id": str(mission["mission_id"]),
      "decisions": [decision("claim_pending_mission", mission_id=str(mission["mission_id"]))],
    }

  async def dispatch_first_task(state: WorkflowState) -> dict:
    mission_id = state.get("assigned_mission_id")
    if mission_id is None:
      return {"decisions": [decision("dispatch_first_task", action="skipped_no_mission")]}

    next_task = await db.find_next_task(pool, mission_id)
    if next_task is None:
      logger.warning(
        f"scheduling_workflow: mission {mission_id} has no tasks; "
        f"leaving mission active but no command issued"
      )
      return {"decisions": [decision("dispatch_first_task", warning="mission_has_no_tasks")]}

    task_id = str(next_task["task_id"])
    receipt = await tools.dispatch_task(
      pool,
      task_id=task_id,
      robot_id=state["event"]["robot_id"],
      mission_id=mission_id,
      task_type=next_task.get("task_type"),
      priority=next_task.get("priority") or 0,
      issued_by="scheduling_workflow",
    )
    await audit_checkpoint(pool, state["workflow_id"], "dispatch_first_task", receipt.to_dict())
    return {
      "next_task_id":    task_id,
      "commands_issued": [receipt.command_id] if receipt.command_id else [],
      "decisions": [decision("dispatch_first_task", **receipt.to_dict())],
    }

  async def finalize(state: WorkflowState) -> dict:
    await terminal.mark_workflow_completed(pool, state["workflow_id"], "finalize")
    return {"status": "completed"}

  graph = StateGraph(WorkflowState)
  graph.add_node("claim_pending_mission", claim_pending_mission)
  graph.add_node("dispatch_first_task",   dispatch_first_task)
  graph.add_node("finalize",              finalize)

  graph.set_entry_point("claim_pending_mission")
  graph.add_edge("claim_pending_mission", "dispatch_first_task")
  graph.add_edge("dispatch_first_task",   "finalize")
  graph.add_edge("finalize", END)
  return graph
