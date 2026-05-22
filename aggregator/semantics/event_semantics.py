"""
Event semantic definitions.

Canonical registry of all events the aggregator can emit.
Each entry is a tuple of (event_type, severity, source_component).

EventDetector imports from here so that event_type strings,
severities, and source labels are never duplicated or hardcoded
across the codebase.
"""

from typing import Tuple

# Type alias for readability
EventDef = Tuple[str, str, str]  # (event_type, severity, source_component)


class Event:

  # ─────────────────────────────────────────────
  # Battery
  # ─────────────────────────────────────────────

  BATTERY_LOW:      EventDef = ("battery_low",      "warning",  "battery_monitor")
  BATTERY_CRITICAL: EventDef = ("battery_critical", "critical", "battery_monitor")

  # ─────────────────────────────────────────────
  # Navigation
  # ─────────────────────────────────────────────

  PATH_BLOCKED:      EventDef = ("path_blocked",      "warning", "navigation_monitor")
  NAVIGATION_FAILED: EventDef = ("navigation_failed", "warning", "navigation_monitor")
  ROBOT_ARRIVED:     EventDef = ("robot_arrived",     "info",    "navigation_monitor")

  # ─────────────────────────────────────────────
  # Operational
  # ─────────────────────────────────────────────

  ROBOT_ERROR:    EventDef = ("robot_error",    "critical", "status_monitor")
  ROBOT_IDLE:     EventDef = ("robot_idle",     "info",     "status_monitor")
  ROBOT_CHARGING: EventDef = ("robot_charging", "info",     "status_monitor")

  # ─────────────────────────────────────────────
  # Health
  # ─────────────────────────────────────────────

  HEALTH_DEGRADED: EventDef = ("health_degraded", "warning",  "health_monitor")
  HEALTH_CRITICAL: EventDef = ("health_critical", "critical", "health_monitor")
