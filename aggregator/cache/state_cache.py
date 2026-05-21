import threading
from typing import Dict, Optional
from aggregator.schemas.models import RobotState


class StateCache:
  """
  In-memory cache of latest robot states.

  Purpose:
  - avoid redundant DB writes when state hasn't meaningfully changed
  - enable transition detection (prev state → current state)
  - provide fast local reads without hitting PostgreSQL

  Thread-safe via per-robot locks.
  """

  def __init__(self):
    self._states: Dict[str, RobotState] = {}
    self._lock = threading.Lock()

  def get(self, robot_id: str) -> Optional[RobotState]:
    with self._lock:
      return self._states.get(robot_id)

  def set(self, state: RobotState) -> None:
    with self._lock:
      self._states[state.robot_id] = state

  def get_field(self, robot_id: str, field: str):
    with self._lock:
      state = self._states.get(robot_id)
      if state is None:
        return None
      return getattr(state, field, None)

  def has_changed(self, robot_id: str, field: str, new_value) -> bool:
    """
    Returns True if the field value differs from cached state.
    Used by monitors to decide whether to write to DB or emit an event.
    """
    current = self.get_field(robot_id, field)
    return current != new_value

  def all_states(self) -> Dict[str, RobotState]:
    with self._lock:
      return dict(self._states)
