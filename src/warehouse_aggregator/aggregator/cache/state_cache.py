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

	# state_cache.py

	def merge_and_set(self, partial: RobotState) -> RobotState:
		"""
		Atomically merge partial state into cached state and return
		the resulting full state. The entire read-decide-write
		sequence is held under one lock.
		"""
		with self._lock:
			cached = self._states.get(partial.robot_id)

			if cached is None:
				self._states[partial.robot_id] = partial
				return partial

			def pick(new_val, cached_val):
				return new_val if new_val is not None else cached_val

			merged = RobotState(
				robot_id=partial.robot_id,
				robot_name=          pick(partial.robot_name,         cached.robot_name),
				x=                   pick(partial.x,                  cached.x),
				y=                   pick(partial.y,                  cached.y),
				theta=               pick(partial.theta,              cached.theta),
				current_zone=        pick(partial.current_zone,       cached.current_zone),
				battery_pct=         pick(partial.battery_pct,        cached.battery_pct),
				operational_status=  pick(partial.operational_status, cached.operational_status),
				navigation_status=   pick(partial.navigation_status,  cached.navigation_status),
				current_mission_id=  pick(partial.current_mission_id, cached.current_mission_id),
				current_task_id=     pick(partial.current_task_id,    cached.current_task_id),
				last_heartbeat=      pick(partial.last_heartbeat,     cached.last_heartbeat),
				health_score=        pick(partial.health_score,       cached.health_score),
			)

			self._states[partial.robot_id] = merged
			return merged

	'''
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
	'''

	def all_states(self) -> Dict[str, RobotState]:
		with self._lock:
			return dict(self._states)