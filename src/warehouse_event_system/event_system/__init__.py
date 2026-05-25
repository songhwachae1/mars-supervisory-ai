"""
Event System

Converts semantic state transitions into orchestration triggers.

Responsibilities:
  1. Event detection      — diff prev/new robot state for meaningful transitions
  2. Event construction   — build full Event objects from candidates
  3. Event severity       — assign operational importance
  4. Event deduplication  — collapse repeated identical events into one workflow
  5. Event persistence    — write to PostgreSQL robot_events
  6. Event dispatch       — NOTIFY orchestrator + fire in-proc subscribers
  7. Event lifecycle      — pending → dispatched → in_progress → terminal

The aggregator submits state transitions; this package owns the rest.
"""

from event_system.pipeline import EventPipeline
from event_system.schemas.models import Event, EventCandidate, StateTransition
from event_system.schemas.statuses import EventStatus
from event_system.schemas.severity import Severity
