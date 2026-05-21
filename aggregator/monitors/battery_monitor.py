import logging
from typing import Callable
from aggregator.schemas.models import RobotState

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

  on_state_update: callback to notify aggregator node of updated state
  """

  # voltage range for normalization when raw voltage is published
  VOLTAGE_MIN = 9.0
  VOLTAGE_MAX = 12.6

  def __init__(self, robot_id: str, on_state_update: Callable[[RobotState], None]):
    self._robot_id = robot_id
    self._on_state_update = on_state_update

  def handle_battery_state(self, msg) -> None:
    """
    Callback for sensor_msgs/BatteryState.
    Fields used: percentage (0.0-1.0) or voltage.
    """
    try:
      battery_pct = self._extract_pct(msg)
      if battery_pct is None:
        return

      state = RobotState(
        robot_id=self._robot_id,
        battery_pct=round(battery_pct, 2),
      )
      self._on_state_update(state)

    except Exception as e:
      logger.error(f"BatteryMonitor error for {self._robot_id}: {e}")

  def _extract_pct(self, msg) -> float:
    """
    Extract battery percentage from message.
    Prefers msg.percentage (0.0-1.0 float).
    Falls back to voltage normalization.
    """
    # sensor_msgs/BatteryState uses percentage field (0.0 to 1.0)
    if hasattr(msg, "percentage") and msg.percentage >= 0:
      return msg.percentage * 100.0

    # fallback: normalize voltage to percentage
    if hasattr(msg, "voltage") and msg.voltage > 0:
      clamped = max(self.VOLTAGE_MIN, min(self.VOLTAGE_MAX, msg.voltage))
      return ((clamped - self.VOLTAGE_MIN) / (self.VOLTAGE_MAX - self.VOLTAGE_MIN)) * 100.0

    logger.warning(f"BatteryMonitor: unreadable message for {self._robot_id}")
    return None
