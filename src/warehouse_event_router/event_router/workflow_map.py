"""
Static event_type → workflow_name routing table.

This is the single source of truth for which workflow handles which
event type. Routing is *deterministic*: no rules, no priorities, no
fallbacks beyond the explicit `None` sentinel.

Add a new workflow:  add a row to WORKFLOW_MAP.
Decommission one:    remove the row.

A `None` value means "this event needs no workflow" — typically an
informational event that the router records as completed without
launching anything (e.g. robot_idle is for observability only).

A missing key means "unmapped" — the router will log a warning and
complete the event with metadata noting that no route was found.
"""

from typing import Dict, Optional


WORKFLOW_MAP: Dict[str, Optional[str]] = {
  # ── Navigation ────────────────────────────
  "path_blocked":      "recovery_workflow",
  "navigation_failed": "recovery_workflow",
  "robot_arrived":     "task_completion_workflow",

  # ── Battery ───────────────────────────────
  "battery_low":       "charging_workflow",
  "battery_critical":  "emergency_charging_workflow",

  # ── Operational ───────────────────────────
  "robot_error":       "diagnostic_workflow",
  "robot_idle":        "scheduling_workflow",
  "robot_charging":    None,  # informational; no workflow needed

  # ── Health ────────────────────────────────
  "health_degraded":   "monitoring_workflow",
  "health_critical":   "diagnostic_workflow",
}
