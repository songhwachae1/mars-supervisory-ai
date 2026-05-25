"""
Severity vocabulary.

Severity is the single signal the orchestrator uses to triage:
  - info       — informational; orchestrator may ignore
  - warning    — degraded but operational; schedule reactively
  - critical   — degraded and blocking; preempt other work
  - emergency  — safety-relevant; immediate halt-and-investigate

These four levels map to operational importance, NOT severity of
the underlying signal. A "battery_low" reading is a warning; the
same reading after a charging failure becomes critical.
"""

from enum import Enum


class Severity(str, Enum):
  INFO      = "info"
  WARNING   = "warning"
  CRITICAL  = "critical"
  EMERGENCY = "emergency"

  @classmethod
  def order(cls, value: str) -> int:
    """
    Numeric rank for comparisons (higher = more severe).
    Used by the classifier to escalate but never demote.
    """
    return _ORDER.get(value, 0)


_ORDER = {
  Severity.INFO.value:      0,
  Severity.WARNING.value:   1,
  Severity.CRITICAL.value:  2,
  Severity.EMERGENCY.value: 3,
}
