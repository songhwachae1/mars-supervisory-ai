"""
Data models used by the event router.

Kept tiny and inert. The router is plumbing, not logic.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ClaimedEvent:
  """
  An event row the router has locked for processing.

  Mirrors the subset of robot_events columns the router actually needs.
  The full row stays in the DB; we don't carry it around.
  """
  event_id: int
  robot_id: str
  event_type: str
  severity: str
  source_component: str
  payload: dict


@dataclass
class WorkflowInput:
  """
  The deterministic input state handed to a LangGraph workflow.

  Three components, in order of certainty:
    - event           : the triggering event (always present)
    - robot_state     : current semantic state of the robot (may be None
                        if the event arrived before any state was
                        written; rare but possible at cold start)
    - active_mission  : the robot's currently-active mission, if any
  """
  event: ClaimedEvent
  robot_state: Optional[dict] = None
  active_mission: Optional[dict] = None

  def to_dict(self) -> dict:
    """LangGraph workflows expect a plain dict as initial state."""
    return {
      "event": {
        "event_id":         self.event.event_id,
        "robot_id":         self.event.robot_id,
        "event_type":       self.event.event_type,
        "severity":         self.event.severity,
        "source_component": self.event.source_component,
        "payload":          self.event.payload,
      },
      "robot_state":    self.robot_state,
      "active_mission": self.active_mission,
    }
