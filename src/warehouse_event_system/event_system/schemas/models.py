"""
Data models for the event system.

  StateTransition — input: a prev/new robot state pair handed in by the aggregator.
  EventCandidate  — output of detection: an unconstructed event hint (no severity yet).
  Event           — fully constructed, ready to persist/dispatch.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ─────────────────────────────────────────────
# State Transition (input to detection)
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class StateTransition:
  """
  A transition from a previous state to a new state for one robot.

  `prev` is None on the robot's first observed state — detection rules
  should treat that as "initial observation" and emit events only if the
  initial state is itself notable (e.g. already in error).
  """
  robot_id: str
  prev: Optional[object] = None  # RobotState (aggregator schema)
  new: object = None             # RobotState (aggregator schema)


# ─────────────────────────────────────────────
# Event Candidate (output of detection)
# ─────────────────────────────────────────────

@dataclass
class EventCandidate:
  """
  A detection rule's output. Carries enough information to build a full
  Event, but no severity or dedup key yet — those are assigned downstream.
  """
  robot_id: str
  event_type: str
  source_component: str
  payload: dict = field(default_factory=dict)
  # Optional severity override from the rule (else looked up by event_type)
  severity_hint: Optional[str] = None


# ─────────────────────────────────────────────
# Event (full, ready to persist)
# ─────────────────────────────────────────────

@dataclass
class Event:
  """
  Fully constructed event, ready to be persisted and dispatched.

  `event_id` is None until persistence assigns one (BIGSERIAL).
  Lifecycle fields (status, dispatched_at, etc.) are mutated by
  LifecycleManager as the event moves through the pipeline.
  """
  robot_id: str
  event_type: str
  severity: str
  source_component: str
  payload: dict = field(default_factory=dict)

  # Set by Deduper
  dedup_key: Optional[str] = None

  # Set after persistence
  event_id: Optional[int] = None

  # Lifecycle (mutated by LifecycleManager)
  status: str = "pending"
  dedup_count: int = 1
  workflow_id: Optional[str] = None
  dispatched_at: Optional[datetime] = None
  completed_at: Optional[datetime] = None
  last_updated_at: datetime = field(default_factory=datetime.utcnow)

  created_at: datetime = field(default_factory=datetime.utcnow)
