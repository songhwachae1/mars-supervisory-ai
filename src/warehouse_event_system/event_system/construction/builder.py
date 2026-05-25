"""
EventBuilder.

Turns an EventCandidate (detection output) into a full Event ready for
the rest of the pipeline. The builder does not write to the DB, doesn't
assign dedup keys, and doesn't classify severity — it only constructs.

Severity is assigned by SeverityClassifier; we feed the candidate's
`severity_hint` through so the classifier has a starting point.
"""

from datetime import datetime
from typing import List

from event_system.schemas.models import Event, EventCandidate
from event_system.severity.classifier import SeverityClassifier


class EventBuilder:

  def __init__(self, severity_classifier: SeverityClassifier):
    self._severity = severity_classifier

  def build(self, candidate: EventCandidate, state) -> Event:
    """
    Construct a full Event. `state` is the new RobotState that produced
    the candidate, passed in so the severity classifier can use it for
    contextual escalation.
    """
    severity = self._severity.classify(candidate, state)
    now = datetime.utcnow()
    return Event(
      robot_id=candidate.robot_id,
      event_type=candidate.event_type,
      severity=severity,
      source_component=candidate.source_component,
      payload=dict(candidate.payload),
      created_at=now,
      last_updated_at=now,
    )

  def build_many(self, candidates: List[EventCandidate], state) -> List[Event]:
    return [self.build(c, state) for c in candidates]
