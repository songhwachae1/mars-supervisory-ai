import logging
import math
from typing import Callable, Dict, Tuple, Optional
from aggregator.schemas.models import RobotState

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Zone Map
# Maps (x, y) bounding boxes to zone labels.
# Extend this with your warehouse floor plan.
# ─────────────────────────────────────────────

# Format: zone_id → (x_min, x_max, y_min, y_max)
ZONE_MAP: Dict[str, Tuple[float, float, float, float]] = {
  "zone_a":   (0.0,  10.0, 0.0,  10.0),
  "zone_b":   (10.0, 20.0, 0.0,  10.0),
  "zone_c":   (0.0,  10.0, 10.0, 20.0),
  "charging": (18.0, 22.0, 18.0, 22.0),
  "entrance": (-2.0,  2.0, -2.0,  2.0),
}


def resolve_zone(x: float, y: float) -> Optional[str]:
  for zone_id, (x_min, x_max, y_min, y_max) in ZONE_MAP.items():
    if x_min <= x <= x_max and y_min <= y <= y_max:
      return zone_id
  return None


class NavigationMonitor:
  """
  Subscribes to navigation and odometry ROS2 topics.

  Topics consumed:
  - /robot_{id}/odom          (nav_msgs/Odometry)
  - /robot_{id}/nav_status    (std_msgs/String or action feedback)

  Raw ROS input     → Semantic output
  ─────────────────────────────────────────────────────────
  Odometry pose     → x, y, theta, current_zone
  nav_status string → navigation_status (navigating | path_blocked | arrived | failed)

  Responsibility:
  - extract position and heading
  - resolve zone from coordinates
  - normalize nav status strings → semantic vocabulary
  - do NOT plan or reason
  """

  # Map raw ROS nav status strings → semantic vocabulary
  NAV_STATUS_MAP = {
    "NAVIGATING":    "navigating",
    "IN_PROGRESS":   "navigating",
    "BLOCKED":       "path_blocked",
    "OBSTACLE":      "path_blocked",
    "SUCCEEDED":     "arrived",
    "ARRIVED":       "arrived",
    "FAILED":        "failed",
    "ABORTED":       "failed",
    "UNKNOWN":       None,
  }

  def __init__(self, robot_id: str, on_state_update: Callable[[RobotState], None]):
    self._robot_id = robot_id
    self._on_state_update = on_state_update

  # ─────────────────────────────────────────────
  # Odometry callback
  # nav_msgs/Odometry
  # ─────────────────────────────────────────────

  def handle_odom(self, msg) -> None:
    try:
      pos = msg.pose.pose.position
      ori = msg.pose.pose.orientation

      x = pos.x
      y = pos.y
      theta = self._yaw_from_quaternion(ori.x, ori.y, ori.z, ori.w)
      zone = resolve_zone(x, y)

      state = RobotState(
        robot_id=self._robot_id,
        x=round(x, 4),
        y=round(y, 4),
        theta=round(theta, 4),
        current_zone=zone,
      )
      self._on_state_update(state)

    except Exception as e:
      logger.error(f"NavigationMonitor odom error for {self._robot_id}: {e}")

  # ─────────────────────────────────────────────
  # Navigation status callback
  # std_msgs/String (or custom status message)
  # ─────────────────────────────────────────────

  def handle_nav_status(self, msg) -> None:
    try:
      raw = msg.data.strip().upper()
      semantic = self.NAV_STATUS_MAP.get(raw)

      if semantic is None:
        logger.debug(f"NavigationMonitor: unmapped nav status '{raw}' for {self._robot_id}")
        return

      state = RobotState(
        robot_id=self._robot_id,
        navigation_status=semantic,
      )
      self._on_state_update(state)

    except Exception as e:
      logger.error(f"NavigationMonitor nav_status error for {self._robot_id}: {e}")

  # ─────────────────────────────────────────────
  # Helpers
  # ─────────────────────────────────────────────

  @staticmethod
  def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    """Extract yaw (rotation around Z axis) from quaternion."""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)
