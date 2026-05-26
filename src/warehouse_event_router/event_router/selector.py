"""
WorkflowSelector.

Pure function over the static WORKFLOW_MAP. Returns one of:

  ("launch",     "<workflow_name>")  — route to this workflow
  ("informational", None)            — event mapped to None; close it out
  ("unmapped",     None)             — event_type not in the map at all

The router uses the tag to decide both what to do and what to log.
"""

from typing import Tuple, Optional

from event_router.workflow_map import WORKFLOW_MAP


SelectorDecision = Tuple[str, Optional[str]]


class WorkflowSelector:

  def select(self, event_type: str) -> SelectorDecision:
    if event_type not in WORKFLOW_MAP:
      return ("unmapped", None)
    workflow = WORKFLOW_MAP[event_type]
    if workflow is None:
      return ("informational", None)
    return ("launch", workflow)
