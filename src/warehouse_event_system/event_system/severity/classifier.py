"""
SeverityClassifier.

Assigns severity to an event candidate. The default behavior is to use
the candidate's static severity_hint (defined in the event_semantics
registry). The classifier additionally applies *context escalation*
rules — never demoting, only raising — when robot context makes the
event more dangerous than its baseline.

Examples of escalation:
  - battery_low while in operational_status == 'error'  → critical
  - path_blocked while battery is already critical       → critical
  - any warning while health_score is critical          → critical
"""

import logging
from typing import Optional

from event_system.schemas.models import EventCandidate
from event_system.schemas.severity import Severity
from event_system.schemas.statuses import EventStatus  # noqa: F401  (re-exported)

logger = logging.getLogger(__name__)


class SeverityClassifier:

  def classify(self, candidate: EventCandidate, state) -> str:
    base = candidate.severity_hint or Severity.WARNING.value
    escalated = self._maybe_escalate(base, candidate, state)
    return escalated

  # ─────────────────────────────────────────────
  # Escalation rules
  # ─────────────────────────────────────────────

  def _maybe_escalate(self, base: str, candidate: EventCandidate, state) -> str:
    """
    Apply contextual escalation. Returns the higher of `base` and any
    rule-produced level. Never demotes.
    """
    rank = Severity.order(base)
    best = base

    for rule in _ESCALATION_RULES:
      try:
        suggested = rule(candidate, state)
      except Exception as e:
        logger.error(f"Escalation rule {rule.__name__} failed: {e}")
        continue

      if suggested is not None and Severity.order(suggested) > rank:
        best = suggested
        rank = Severity.order(suggested)

    return best


# ─────────────────────────────────────────────
# Rule definitions
# Each rule returns a suggested severity or None.
# ─────────────────────────────────────────────

def _rule_warning_on_error_state(candidate: EventCandidate, state) -> Optional[str]:
  if state is None:
    return None
  if getattr(state, "operational_status", None) == "error":
    return Severity.CRITICAL.value
  return None


def _rule_blocked_on_low_battery(candidate: EventCandidate, state) -> Optional[str]:
  if state is None or candidate.event_type != "path_blocked":
    return None
  pct = getattr(state, "battery_pct", None)
  if pct is not None and pct <= 10.0:
    return Severity.CRITICAL.value
  return None


def _rule_critical_health_promotes_all(candidate: EventCandidate, state) -> Optional[str]:
  if state is None:
    return None
  health = getattr(state, "health_score", 1.0)
  if health is not None and health <= 0.3:
    return Severity.CRITICAL.value
  return None


_ESCALATION_RULES = [
  _rule_warning_on_error_state,
  _rule_blocked_on_low_battery,
  _rule_critical_health_promotes_all,
]
