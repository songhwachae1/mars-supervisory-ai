import logging
from typing import List, Optional

from aggregator.schemas.models import RobotState, RobotEvent
from aggregator.cache.state_cache import StateCache
from aggregator.semantics import (
  BATTERY_LOW_PCT,
  BATTERY_CRITICAL_PCT,
  HEALTH_DEGRADED,
  HEALTH_CRITICAL,
)
from aggregator.semantics.event_semantics import Event

logger = logging.getLogger(__name__)


class EventDetector:
  """
  Detects semantic events by comparing incoming state
  against cached previous state.

  Rules:
  - Only emits an event when a meaningful transition occurs
  - Does NOT plan, reason, or call LLMs
  - Returns a list of RobotEvent objects for DBWriter to persist
  """

  def __init__(self, cache: StateCache):
    self._cache = cache

  def detect(self, new_state: RobotState) -> List[RobotEvent]:
    events: List[RobotEvent] = []
    prev = self._cache.get(new_state.robot_id)

    events += self._check_battery(new_state, prev)
    events += self._check_navigation(new_state, prev)
    events += self._check_operational_status(new_state, prev)
    events += self._check_health(new_state, prev)

    return events

  # ─────────────────────────────────────────────
  # Battery
  # ─────────────────────────────────────────────

  def _check_battery(
    self,
    new: RobotState,
    prev: Optional[RobotState]
  ) -> List[RobotEvent]:
    events = []
    if new.battery_pct is None:
      return events

    prev_pct = prev.battery_pct if prev else None

    if new.battery_pct <= BATTERY_CRITICAL_PCT:
      if prev_pct is None or prev_pct > BATTERY_CRITICAL_PCT:
        events.append(self._make_event(new, Event.BATTERY_CRITICAL, {
          "battery_pct": new.battery_pct,
        }))

    elif new.battery_pct <= BATTERY_LOW_PCT:
      if prev_pct is None or prev_pct > BATTERY_LOW_PCT:
        events.append(self._make_event(new, Event.BATTERY_LOW, {
          "battery_pct": new.battery_pct,
        }))

    return events

  # ─────────────────────────────────────────────
  # Navigation
  # ─────────────────────────────────────────────

  def _check_navigation(
    self,
    new: RobotState,
    prev: Optional[RobotState]
  ) -> List[RobotEvent]:
    events = []
    if new.navigation_status is None:
      return events

    prev_nav = prev.navigation_status if prev else None
    if new.navigation_status == prev_nav:
      return events

    location_payload = {"x": new.x, "y": new.y, "zone": new.current_zone}

    if new.navigation_status == "path_blocked":
      events.append(self._make_event(new, Event.PATH_BLOCKED, location_payload))

    elif new.navigation_status == "failed":
      events.append(self._make_event(new, Event.NAVIGATION_FAILED, location_payload))

    elif new.navigation_status == "arrived":
      events.append(self._make_event(new, Event.ROBOT_ARRIVED, {
        "zone": new.current_zone,
      }))

    return events

  # ─────────────────────────────────────────────
  # Operational Status
  # ─────────────────────────────────────────────

  def _check_operational_status(
    self,
    new: RobotState,
    prev: Optional[RobotState]
  ) -> List[RobotEvent]:
    events = []
    if new.operational_status is None:
      return events

    prev_status = prev.operational_status if prev else None
    if new.operational_status == prev_status:
      return events

    if new.operational_status == "error":
      events.append(self._make_event(new, Event.ROBOT_ERROR, {
        "operational_status": new.operational_status,
      }))

    elif new.operational_status == "idle" and prev_status == "busy":
      events.append(self._make_event(new, Event.ROBOT_IDLE, {}))

    elif new.operational_status == "charging":
      events.append(self._make_event(new, Event.ROBOT_CHARGING, {
        "battery_pct": new.battery_pct,
      }))

    return events

  # ─────────────────────────────────────────────
  # Health
  # ─────────────────────────────────────────────

  def _check_health(
    self,
    new: RobotState,
    prev: Optional[RobotState]
  ) -> List[RobotEvent]:
    events = []
    if new.health_score is None:
      return events

    prev_health = prev.health_score if prev else 1.0

    if new.health_score <= HEALTH_CRITICAL and prev_health > HEALTH_CRITICAL:
      events.append(self._make_event(new, Event.HEALTH_CRITICAL, {
        "health_score": new.health_score,
      }))

    elif new.health_score <= HEALTH_DEGRADED and prev_health > HEALTH_DEGRADED:
      events.append(self._make_event(new, Event.HEALTH_DEGRADED, {
        "health_score": new.health_score,
      }))

    return events

  # ─────────────────────────────────────────────
  # Helper
  # ─────────────────────────────────────────────

  @staticmethod
  def _make_event(state: RobotState, event_def: tuple, payload: dict) -> RobotEvent:
    event_type, severity, source_component = event_def
    return RobotEvent(
      robot_id=state.robot_id,
      event_type=event_type,
      severity=severity,
      source_component=source_component,
      payload=payload,
    )
