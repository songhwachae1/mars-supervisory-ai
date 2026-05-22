"""
Operational status semantic definitions.

Defines how raw ROS operational status strings
map to the semantic vocabulary used across the system.
"""

from typing import Dict


# ─────────────────────────────────────────────
# Operational Status Map
# Raw ROS string → semantic vocabulary
# ─────────────────────────────────────────────

OPERATIONAL_STATUS_MAP: Dict[str, str] = {
  "IDLE":     "idle",
  "BUSY":     "busy",
  "CHARGING": "charging",
  "ERROR":    "error",
}
