"""
warehouse_workflows

LangGraph workflows launched by the event router.

Public surface:
  - WorkflowRuntime          : starts the checkpointer, builds the registry,
                               and invokes workflows by name.
  - WorkflowState            : the TypedDict every graph operates on.
  - UnknownWorkflow          : raised when a workflow_name has no graph.

Per-workflow code lives in workflows/graphs/<name>.py.
The static name → graph mapping lives in workflows/registry.py.
"""

from workflows.runtime import WorkflowRuntime, UnknownWorkflow
from workflows.state import WorkflowState
