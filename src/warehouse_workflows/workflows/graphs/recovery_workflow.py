"""
recovery_workflow

Triggered by:
  - path_blocked
  - navigation_failed

Nodes:
  assess_blockage  → classify transient vs chronic; insert anomaly for chronic
  plan_reroute     → package reroute intent (destination + recovery_attempt counter)
  issue_reroute    → call navigate_to tool with reroute intent
  finalize         → mark workflow_execution completed/failed

To activate, add to workflows/registry.py:
    "recovery_workflow": recovery_workflow.build_graph,
"""

import logging

import asyncpg
import os
from langgraph.graph import END, StateGraph
from langchain_anthropic import ChatAnthropic
from dotenv import load_dotenv

from workflows import db, terminal, tools
from workflows.graphs._shared import audit_checkpoint, decision
from workflows.state import WorkflowState

logger = logging.getLogger(__name__)

BLOCKAGE_WINDOW_S    = 60   # how recent counts as "recent"
RECURRENCE_THRESHOLD = 2    # 3rd hit (this one + 2 prior) → escalate


def build_graph(pool: asyncpg.Pool) -> StateGraph:
	load_dotenv()
	model_version = os.getenv("ANTHROPIC_MODEL")
	llm = ChatAnthropic(model=model_version, temperature=0)
		
  async def assess_blockage(state: WorkflowState) -> dict:
    robot_id = (state.get("robot_state") or {}).get("robot_id")
    event    = state["event"]
    event_id = event["event_id"]

    event_summ = await db.count_recent_blockage_events(pool, robot_id, BLOCKAGE_WINDOW_S, event_id)
		block_cnt = event_summ["event_count"]
    if event_summ["event_count"] >= RECURRENCE_THRESHOLD:
      block_type = "chronic"
      receipt = await tools.record_anomaly(
        pool,
        robot_id=robot_id,
        anomaly_type="chronic_blockage",
        severity="high",
        detected_by="recovery_workflow",
        related_event_id=event_id,
        description="chronic blockage detected by recovery_workflow",
        state_snapshot={
          "robot_state":    state.get("robot_state"),
          "active_mission": state.get("active_mission"),
          "event_payload":  event.get("payload"),
					"recent_block_cnt": block_cnt,
        },
      )
      await audit_checkpoint(pool, state["workflow_id"], "assess_blockage", {
        "blockage_type": block_type,
				"recent_block_cnt": block_cnt
        **receipt.to_dict(),
      })
      return {
        "blockage_type": block_type,
        "anomaly_id":    receipt.meta["anomaly_id"],
				"recent_block_cnt": block_cnt,
        "decisions": [decision("assess_blockage", blockage_type=block_type, **receipt.to_dict())],
      }

    block_type = "transient"
    await audit_checkpoint(pool, state["workflow_id"], "assess_blockage", {"blockage_type": block_type})
    return {
      "blockage_type": block_type,
			"recent_block_cnt": block_cnt,
      "decisions": [decision("assess_blockage", blockage_type=block_type)],
    }

  async def navigation_recovery_agent(state: WorkflowState) -> dict:
		prior_attempt = (state["event"].get("payload") or {}).get("recovery_attempt", 0)
		robot_id = (state.get("robot_state") or {}).get("robot_id")
		mission = state.get("active_mission")

    if mission is None:
      message = "The robot does not have a mission"
    
    else:
      mission_str = mission.get("mission_name", "unknown mission")
  
      message = (
          f"The robot's mission is {mission_str}."
      )
  
      dest_shelf = mission.get(
          "destination_location"
      )
  
      if dest_shelf:
          message += (
              f" The robot is heading to {dest_shelf}."
          )

		prompt = f"""
		You are a robot navigation recovery agent.
		{robot_id} is experiencing {state.get("blockage_type")} blockage.
		The event has occured {state.get("recent_block_cnt")} times in {BLOCKAGE_WINDOW_S} seconds.
		{message}
		
		Allowed actions:

    retry
    reroute
    wait
    abort

		- If chronic blockage and attempts ≥3:
      prefer reroute
    
    - If battery < 15:
      avoid wait
    
    - If mission absent:
      abort
    
    - Never invent actions

		Output JSON.
		The output JSON should have "action", "reason", "confidence"

		"""
		result = await llm.ainvoke(prompt)
		await audit_checkpoint(pool, state["workflow_id"], "navigation_recovery_agent", {"answer": result})
		ret = {}
		ret["answer"] = result
		ret["decisions"] = [decision("navigation_recovery_agent", llm_result=result)]
		return ret

  async def route_recovery(state: WorkflowState) -> dict:
		answer = state.get("answer")
		if answer["action"] == "retry":
			return "retry"
		elif answer["action"] == "reroute":
			return "reroute"
		elif answer["action"] == "wait":
			return "wait"
		else:
			return "abort"

	async def plan_reroute(state: WorkflowState) -> dict:
    """
    Package reroute intent: same destination, incremented recovery_attempt.
    Coordinate resolution is the tool's responsibility — this node only
    confirms the intent can be formed (mission + destination exist in state).
    """
    mission = state.get("active_mission")
    if mission is None:
      await audit_checkpoint(pool, state["workflow_id"], "plan_reroute", {"reason": "no_mission_available"})
      return {
        "error":   "no_mission_available",
        "decisions": [decision("plan_reroute", reason="no_mission_available")],
      }

    dest_shelf = mission.get("destination_location")
    if dest_shelf is None:
      await audit_checkpoint(pool, state["workflow_id"], "plan_reroute", {"reason": "no_destination_in_mission"})
      return {
        "error":   "no_destination_in_mission",
        "decisions": [decision("plan_reroute", reason="no_destination_in_mission")],
      }

    prior_attempt = (state["event"].get("payload") or {}).get("recovery_attempt", 0)
    reroute_target = {
      "destination_shelf_id": dest_shelf,
      "recovery_attempt":     prior_attempt + 1,
    }

    await audit_checkpoint(pool, state["workflow_id"], "plan_reroute", reroute_target)
    return {
      "reroute_target": reroute_target,
      "decisions": [decision("plan_reroute", **reroute_target)],
    }

  async def issue_wait(state: WorkflowState) -> dict:
		mission = state.get("active_mission")
    if mission is None:
      return {
        "error":   "no_mission_available",
        "decisions": [decision("issue_reroute", reason="no_mission_available")],
      }

		mid = mission["mission_id"]
    if hasattr(mid, "hex"):  # UUID → str
      mid = str(mid)
		
		pause_receipt = await tools.pause_mission(pool, mission_id=mid, reason=state["answer"]["reason"])

		await audit_checkpoint(pool, state["workflow_id"], "issue_reroute", {
      "wait":   pause_receipt.to_dict(),
    })

		return {
      "mission_paused": mid,
      "decisions": [decision(
        "issue_wait",
        wait=pause_receipt.to_dict(),
      )],
    }
	
	async def issue_reroute(state: WorkflowState) -> dict:
    reroute_target = state.get("reroute_target")
    if reroute_target is None:
      return {
        "error":   "no_reroute_target",
        "decisions": [decision("issue_reroute", reason="no_reroute_target")],
      }

    mission = state.get("active_mission")
    if mission is None:
      return {
        "error":   "no_mission_available",
        "decisions": [decision("issue_reroute", reason="no_mission_available")],
      }

    mid = mission["mission_id"]
    if hasattr(mid, "hex"):  # UUID → str
      mid = str(mid)

    resume_receipt = await tools.resume_mission(pool, mission_id=mid)
    nav_receipt = await tools.navigate_to(
      pool,
      robot_id=state["event"]["robot_id"],
      destination_shelf_id=reroute_target["destination_shelf_id"],
      reason="transient_blockage",
      urgency="recovery",
      recovery_attempt=reroute_target["recovery_attempt"],
      issued_by="recovery_workflow",
    )

    if not nav_receipt.accepted:
      return {
        "error":   nav_receipt.rejection_reason,
        "decisions": [decision("issue_reroute", resume=resume_receipt.to_dict(), navigate=nav_receipt.to_dict())],
      }

    await audit_checkpoint(pool, state["workflow_id"], "issue_reroute", {
      "resume":   resume_receipt.to_dict(),
      "navigate": nav_receipt.to_dict(),
    })
    return {
      "commands_issued": [nav_receipt.command_id],
      "decisions": [decision(
        "issue_reroute",
        resume=resume_receipt.to_dict(),
        navigate=nav_receipt.to_dict(),
      )],
    }

  def route_after_assess(state: WorkflowState):
    if state.get("error") or state.get("blockage_type") == "chronic":
      return "finalize"
    return "plan_reroute"

  def route_after_plan(state: WorkflowState):
    if state.get("error"):
      return "finalize"
    return "issue_reroute"

  async def finalize(state: WorkflowState) -> dict:
    if state.get("error") or state.["answer"]["action"] == "abort":
      await terminal.mark_workflow_failed(pool, state["workflow_id"], "finalize")
      logger.error(
        f"recovery_workflow failed: workflow_id={state['workflow_id']} "
        f"error={state.get('error')} blockage_type={state.get('blockage_type')}"
      )
      return {"status": "failed"}
    await terminal.mark_workflow_completed(pool, state["workflow_id"], "finalize")
    return {"status": "completed"}

  graph = StateGraph(WorkflowState)
  graph.add_node("assess_blockage", assess_blockage)
  graph.add_node("navigation_recovery_agent", navigation_recovery_agent)
  graph.add_node("plan_reroute",    plan_reroute)
  graph.add_node("issue_reroute",   issue_reroute)
  graph.add_node("issue_wait",      issue_wait)
  graph.add_node("finalize",        finalize)

  graph.set_entry_point("assess_blockage")
	graph.add_edge("assess_blockage", "navigation_recovery_agent")
  graph.add_conditional_edges("navigation_recovery_agent", route_recovery, {
    "retry":     "plan_reroute",
    "reroute": "plan_reroute",
    "wait": "issue_wait",
    "abort": "finalize",
  })
  graph.add_conditional_edges("plan_reroute", route_after_plan, {
    "finalize":     "finalize",
    "issue_reroute": "issue_reroute",
  })
	graph.add_edge("issue_wait", "finalize")
  graph.add_edge("issue_reroute", "finalize")
  graph.add_edge("finalize", END)

  return graph
