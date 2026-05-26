"""
task_completion_workflow

Triggered by:  robot_arrived

Plan:
  1. complete_current_task — if the robot is on a task, mark it done.
  2. advance_mission       — find the next task in the mission and
                             activate it. If no more tasks, complete
                             the mission.
  3. finalize              — close out workflow_execution.

Conditional edge: if there is no current_task_id at step 1, we still
run advance_mission — the robot may have arrived at a destination
that's just a position update, not a task completion. The orchestrator
should still try to find the next task.
"""

import logging

import asyncpg
from langgraph.graph import StateGraph, END

from workflows import db, terminal
from workflows.graphs._shared import decision, audit_checkpoint
from workflows.state import WorkflowState

logger = logging.getLogger(__name__)


def build_graph(pool: asyncpg.Pool) -> StateGraph:

  async def complete_current_task(state: WorkflowState) -> dict:
    robot_state = state.get("robot_state") or {}
    task_id = robot_state.get("current_task_id")
    if not task_id:
      return {"decisions": [decision("complete_current_task", action="skipped_no_task")]}

    task_id_s = str(task_id)
    await db.complete_task(pool, task_id_s)
    await audit_checkpoint(pool, state["workflow_id"], "complete_current_task", {"task_id": task_id_s})
    return {
      "completed_task_id": task_id_s,
      "decisions": [decision("complete_current_task", task_id=task_id_s)],
    }

  async def advance_mission(state: WorkflowState) -> dict:
    mission = state.get("active_mission")
    if mission is None:
      return {"decisions": [decision("advance_mission", action="skipped_no_mission")]}

    mid = str(mission["mission_id"])
    next_task = await db.find_next_task(pool, mid)

    if next_task is None:
      # No more tasks → mission is done.
      await db.complete_mission(pool, mid)
      await audit_checkpoint(pool, state["workflow_id"], "advance_mission", {"mission_completed": mid})
      return {"decisions": [decision("advance_mission", mission_completed=mid)]}

    next_id = str(next_task["task_id"])
    await db.activate_task(pool, next_id)
    await audit_checkpoint(pool, state["workflow_id"], "advance_mission", {"activated_task": next_id})
    return {
      "next_task_id": next_id,
      "decisions": [decision("advance_mission", activated_task=next_id, sequence=next_task.get("sequence_order"))],
    }

  async def finalize(state: WorkflowState) -> dict:
    await terminal.mark_workflow_completed(pool, state["workflow_id"], "finalize")
    return {"status": "completed"}

  graph = StateGraph(WorkflowState)
  graph.add_node("complete_current_task", complete_current_task)
  graph.add_node("advance_mission",       advance_mission)
  graph.add_node("finalize",              finalize)

  graph.set_entry_point("complete_current_task")
  graph.add_edge("complete_current_task", "advance_mission")
  graph.add_edge("advance_mission",       "finalize")
  graph.add_edge("finalize", END)
  return graph
