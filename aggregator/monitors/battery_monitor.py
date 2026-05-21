import logging
from typing import Callable, Optional

from aggregator.schemas.models import RobotState
from aggregator.semantics.thresholds import (
  BATTERY_VOLTAGE_MIN,
  BATTERY_VOLTAGE_MAX,
)

logger = logging.getLogger(__name__)


class BatteryMonitor:
  """
  Subscribes to battery ROS2 topics and produces normalized battery_pct.

  Raw ROS input  → Semantic output
  ───────────────────────────────────
  BatteryState   → battery_pct (0-100 float)

  Responsibility:
  - normalize voltage or percentage from sensor message
  - update RobotState.battery_pct
  - do NOT plan or reason
  """

  def __init__(self, robot_id: str, on_state_update: Callable[[RobotState], None]):
    self._robot_id = robot_id
    self._on_state_update = on_state_update

  def handle_battery_state(self, msg) -> None:
    """Callback for sensor_msgs/BatteryState."""
    try:
      battery_pct = self._extract_pct(msg)
      if battery_pct is None:
        return

      self._on_state_update(RobotState(
        robot_id=self._robot_id,
        battery_pct=round(battery_pct, 2),
      ))

    except Exception as e:
      logger.error(f"BatteryMonitor error for {self._robot_id}: {e}")

  def _extract_pct(self, msg) -> Optional[float]:
    """
    Extract battery percentage from message.
    Prefers msg.percentage (0.0-1.0).
    Falls back to voltage normalization.
    """
    if hasattr(msg, "percentage") and msg.percentage >= 0:
      return msg.percentage * 100.0

    if hasattr(msg, "voltage") and msg.voltage > 0:
      clamped = max(BATTERY_VOLTAGE_MIN, min(BATTERY_VOLTAGE_MAX, msg.voltage))
      return ((clamped - BATTERY_VOLTAGE_MIN) / (BATTERY_VOLTAGE_MAX - BATTERY_VOLTAGE_MIN)) * 100.0

    logger.warning(f"BatteryMonitor: unreadable message for {self._robot_id}")
    return None
