"""
WorkflowState — the shared LangGraph state TypedDict.

Inputs are written by the launcher; node functions return partial
state dicts that LangGraph merges in.

Two fields use additive reducers (Annotated[..., add]) so multiple
nodes can append without overwriting each other:
  - decisions       : the per-node audit log
  - commands_issued : agent_command IDs the workflow created

Everything else uses LangGraph's default last-write-wins semantics.
"""

from operator import add
from typing import Annotated, List, Optional, TypedDict


class WorkflowState(TypedDict, total=False):
  # ── Inputs (set by launcher) ──
  event:          dict
  robot_state:    Optional[dict]
  active_mission: Optional[dict]
  workflow_id:    str          # UUID string

  # ── Accumulating fields ──
  decisions:       Annotated[List[dict], add]
  commands_issued: Annotated[List[str],  add]

  # ── Workflow-local scratch (per-graph; keys vary) ──
  selected_charger:   Optional[dict]
  paused_mission_id:  Optional[str]
  completed_task_id:  Optional[str]
  next_task_id:       Optional[str]
  assigned_mission_id: Optional[str]
  anomaly_id:         Optional[str]
  blockage_type:      Optional[str]   # 'transient' | 'chronic'
  reroute_target:     Optional[dict]  # {destination_shelf_id, recovery_attempt}

  # ── Terminal ──
  status: str                  # 'completed' | 'failed' (set by finalize)
  error:  Optional[str]
