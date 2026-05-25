"""
Event lifecycle states.

  pending      → just persisted, awaiting dispatch
  dispatched   → notification sent to orchestrator
  in_progress  → orchestrator has accepted; workflow is running
  completed    → workflow finished successfully
  failed       → workflow terminated with failure
  expired      → no orchestrator picked it up before timeout
  suppressed   → never dispatched as its own row (dedup absorbed it)

Open states  = {pending, dispatched, in_progress}
Terminal    = {completed, failed, expired, suppressed}
"""

from enum import Enum
from typing import Set


class EventStatus(str, Enum):
  PENDING     = "pending"
  DISPATCHED  = "dispatched"
  IN_PROGRESS = "in_progress"
  COMPLETED   = "completed"
  FAILED      = "failed"
  EXPIRED     = "expired"
  SUPPRESSED  = "suppressed"


OPEN_STATES: Set[str] = {
  EventStatus.PENDING.value,
  EventStatus.DISPATCHED.value,
  EventStatus.IN_PROGRESS.value,
}

TERMINAL_STATES: Set[str] = {
  EventStatus.COMPLETED.value,
  EventStatus.FAILED.value,
  EventStatus.EXPIRED.value,
  EventStatus.SUPPRESSED.value,
}


# Valid forward transitions. Backwards transitions are rejected by
# LifecycleManager. Terminal states have no outgoing transitions.
ALLOWED_TRANSITIONS = {
  EventStatus.PENDING.value:     {EventStatus.DISPATCHED.value, EventStatus.EXPIRED.value, EventStatus.SUPPRESSED.value},
  EventStatus.DISPATCHED.value:  {EventStatus.IN_PROGRESS.value, EventStatus.FAILED.value, EventStatus.EXPIRED.value},
  EventStatus.IN_PROGRESS.value: {EventStatus.COMPLETED.value, EventStatus.FAILED.value},
}
