"""
StateTransitionDetector.

Runs every registered detection rule against a (prev, new) state pair
and returns the union of EventCandidates.

This class is the only place that knows about the rule registry; the
rest of the pipeline depends only on EventCandidate.
"""

import logging
from typing import List

from event_system.detection.rules import DETECTION_RULES, DetectionRule
from event_system.schemas.models import EventCandidate, StateTransition

logger = logging.getLogger(__name__)


class StateTransitionDetector:

  def __init__(self, rules: List[DetectionRule] = None):
    self._rules = rules if rules is not None else DETECTION_RULES

  def detect(self, transition: StateTransition) -> List[EventCandidate]:
    out: List[EventCandidate] = []
    for rule in self._rules:
      try:
        out.extend(rule(transition.prev, transition.new))
      except Exception as e:
        # A buggy rule must not break the whole pipeline.
        logger.error(
          f"Detection rule {rule.__name__} failed for {transition.robot_id}: {e}"
        )
    return out
