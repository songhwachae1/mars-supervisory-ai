"""
Navigation semantic definitions.

Defines:
- how raw ROS navigation status strings map to semantic vocabulary
- warehouse zone bounding boxes and zone resolver
"""

from typing import Dict, Optional, Tuple


# ─────────────────────────────────────────────
# Navigation Status Map
# Raw ROS string → semantic vocabulary
# ─────────────────────────────────────────────

NAV_STATUS_MAP: Dict[str, Optional[str]] = {
  "NAVIGATING":  "navigating",
  "IN_PROGRESS": "navigating",
  "BLOCKED":     "path_blocked",
  "OBSTACLE":    "path_blocked",
  "SUCCEEDED":   "arrived",
  "ARRIVED":     "arrived",
  "FAILED":      "failed",
  "ABORTED":     "failed",
  "UNKNOWN":     None,
}


# ─────────────────────────────────────────────
# Warehouse Zone Map
# Format: zone_id → (x_min, x_max, y_min, y_max)
# Update bounding boxes to match your warehouse floor plan.
# ─────────────────────────────────────────────

ZONE_MAP: Dict[str, Tuple[float, float, float, float]] = {
  "zone_a":   (0.0,   10.0,  0.0,  10.0),
  "zone_b":   (10.0,  20.0,  0.0,  10.0),
  "zone_c":   (0.0,   10.0,  10.0, 20.0),
  "charging": (18.0,  22.0,  18.0, 22.0),
  "entrance": (-2.0,   2.0,  -2.0,  2.0),
}


def resolve_zone(x: float, y: float) -> Optional[str]:
  """
  Return the zone_id whose bounding box contains (x, y).
  Returns None if the position falls outside all defined zones.
  """
  for zone_id, (x_min, x_max, y_min, y_max) in ZONE_MAP.items():
    if x_min <= x <= x_max and y_min <= y <= y_max:
      return zone_id
  return None
