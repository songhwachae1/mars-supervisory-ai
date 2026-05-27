"""
Workflow registry.

Static map of `workflow_name → graph factory`. The router never
constructs graphs directly — it asks the runtime, which asks this
map.

Adding a workflow:
  1. Implement `build_graph(pool) -> StateGraph` in workflows/graphs/<name>.py
  2. Register here.

Missing entries are caught by the runtime, which raises
UnknownWorkflow — the router translates that into a workflow_execution
row marked 'failed' with current_node='unknown_workflow'.
"""

from typing import Callable, Dict

import asyncpg
from langgraph.graph import StateGraph

from workflows.graphs import (
  charging_workflow,
  emergency_charging_workflow,
  task_completion_workflow,
  diagnostic_workflow,
  scheduling_workflow,
  monitoring_workflow,
  recovery_workflow,
)


GraphFactory = Callable[[asyncpg.Pool], StateGraph]


WORKFLOW_REGISTRY: Dict[str, GraphFactory] = {
  "charging_workflow":           charging_workflow.build_graph,
  "emergency_charging_workflow": emergency_charging_workflow.build_graph,
  "task_completion_workflow":    task_completion_workflow.build_graph,
  "diagnostic_workflow":         diagnostic_workflow.build_graph,
  "scheduling_workflow":         scheduling_workflow.build_graph,
  "monitoring_workflow":         monitoring_workflow.build_graph,
  "recovery_workflow":           recovery_workflow.build_graph,
}
