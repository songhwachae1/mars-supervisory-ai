import logging
import math
from typing import Callable

from aggregator.schemas.models import RobotState
from aggregator.semantics.navigation_semantics import NAV_STATUS_MAP, resolve_zone

logger = logging.getLogger(__name__)


class NavigationMonitor:
  """
  Subscribes to navigation and odometry ROS2 topics.

  Topics consumed:
  - /{robot_id}/odom          (nav_msgs/Odometry)
  - /{robot_id}/nav_status    (std_msgs/String)

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

  def __init__(self, robot_id: str, on_state_update: Callable[[RobotState], None]):
    self._robot_id = robot_id
    self._on_state_update = on_state_update

  # ─────────────────────────────────────────────
  # Odometry callback
  # ─────────────────────────────────────────────

  def handle_odom(self, msg) -> None:
    try:
      pos = msg.pose.pose.position
      ori = msg.pose.pose.orientation

      x = pos.x
      y = pos.y
      theta = self._yaw_from_quaternion(ori.x, ori.y, ori.z, ori.w)

      self._on_state_update(RobotState(
        robot_id=self._robot_id,
        x=round(x, 4),
        y=round(y, 4),
        theta=round(theta, 4),
        current_zone=resolve_zone(x, y),
      ))

    except Exception as e:
      logger.error(f"NavigationMonitor odom error for {self._robot_id}: {e}")

  # ─────────────────────────────────────────────
  # Navigation status callback
  # ─────────────────────────────────────────────

  def handle_nav_status(self, msg) -> None:
    try:
      raw = msg.data.strip().upper()
      semantic = NAV_STATUS_MAP.get(raw)

      if semantic is None:
        logger.debug(f"NavigationMonitor: unmapped nav status '{raw}' for {self._robot_id}")
        return

      self._on_state_update(RobotState(
        robot_id=self._robot_id,
        navigation_status=semantic,
      ))

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
