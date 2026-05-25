"""
Detection rules.

Each rule is a pure function over (prev_state, new_state) that returns
a list of EventCandidates. Rules MUST NOT:

  - mutate state
  - perform I/O
  - call LLMs
  - assign severity (that's the classifier's job)

Rules SHOULD:

  - emit an event only when a meaningful transition occurs (edge-trigger)
  - be defensive about missing fields on `prev` (first observation)

The thresholds and event-type constants are imported from the aggregator's
semantic vocabulary so the two layers can never drift.
"""

from typing import List, Optional, Callable

from aggregator.schemas.models import RobotState
from aggregator.semantics import (
  BATTERY_LOW_PCT,
  BATTERY_CRITICAL_PCT,
  HEALTH_DEGRADED,
  HEALTH_CRITICAL,
)
from aggregator.semantics.event_semantics import Event as EventDef

from event_system.schemas.models import EventCandidate


# A rule takes (prev, new) and returns 0+ candidates.
DetectionRule = Callable[[Optional[RobotState], RobotState], List[EventCandidate]]


# ─────────────────────────────────────────────
# Battery
# ─────────────────────────────────────────────

def detect_battery(prev: Optional[RobotState], new: RobotState) -> List[EventCandidate]:
  if new.battery_pct is None:
    return []

  prev_pct = prev.battery_pct if prev else None
  out: List[EventCandidate] = []

  if new.battery_pct <= BATTERY_CRITICAL_PCT:
    if prev_pct is None or prev_pct > BATTERY_CRITICAL_PCT:
      out.append(_candidate(new, EventDef.BATTERY_CRITICAL, {"battery_pct": new.battery_pct}))
  elif new.battery_pct <= BATTERY_LOW_PCT:
    if prev_pct is None or prev_pct > BATTERY_LOW_PCT:
      out.append(_candidate(new, EventDef.BATTERY_LOW, {"battery_pct": new.battery_pct}))

  return out


# ─────────────────────────────────────────────
# Navigation
# ─────────────────────────────────────────────

def detect_navigation(prev: Optional[RobotState], new: RobotState) -> List[EventCandidate]:
  if new.navigation_status is None:
    return []

  prev_nav = prev.navigation_status if prev else None
  if new.navigation_status == prev_nav:
    return []

  loc = {"x": new.x, "y": new.y, "zone": new.current_zone}

  if new.navigation_status == "path_blocked":
    return [_candidate(new, EventDef.PATH_BLOCKED, loc)]
  if new.navigation_status == "failed":
    return [_candidate(new, EventDef.NAVIGATION_FAILED, loc)]
  if new.navigation_status == "arrived":
    return [_candidate(new, EventDef.ROBOT_ARRIVED, {"zone": new.current_zone})]
  return []


# ─────────────────────────────────────────────
# Operational status
# ─────────────────────────────────────────────

def detect_operational(prev: Optional[RobotState], new: RobotState) -> List[EventCandidate]:
  if new.operational_status is None:
    return []

  prev_status = prev.operational_status if prev else None
  if new.operational_status == prev_status:
    return []

  if new.operational_status == "error":
    return [_candidate(new, EventDef.ROBOT_ERROR, {"operational_status": new.operational_status})]
  if new.operational_status == "idle" and prev_status == "busy":
    return [_candidate(new, EventDef.ROBOT_IDLE, {})]
  if new.operational_status == "charging":
    return [_candidate(new, EventDef.ROBOT_CHARGING, {"battery_pct": new.battery_pct})]
  return []


# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────

def detect_health(prev: Optional[RobotState], new: RobotState) -> List[EventCandidate]:
  if new.health_score is None:
    return []

  prev_health = prev.health_score if prev else 1.0
  out: List[EventCandidate] = []

  if new.health_score <= HEALTH_CRITICAL and prev_health > HEALTH_CRITICAL:
    out.append(_candidate(new, EventDef.HEALTH_CRITICAL, {"health_score": new.health_score}))
  elif new.health_score <= HEALTH_DEGRADED and prev_health > HEALTH_DEGRADED:
    out.append(_candidate(new, EventDef.HEALTH_DEGRADED, {"health_score": new.health_score}))

  return out


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _candidate(state: RobotState, event_def: tuple, payload: dict) -> EventCandidate:
  event_type, severity, source = event_def
  return EventCandidate(
    robot_id=state.robot_id,
    event_type=event_type,
    source_component=source,
    payload=payload,
    severity_hint=severity,
  )


# Registry — extend by appending. Order doesn't matter; all rules run.
DETECTION_RULES: List[DetectionRule] = [
  detect_battery,
  detect_navigation,
  detect_operational,
  detect_health,
]
