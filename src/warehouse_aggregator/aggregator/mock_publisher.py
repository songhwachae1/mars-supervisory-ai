"""
Mock ROS2 publisher for local development.

Simulates what Isaac Sim would publish so you can develop
and test the aggregator without your partner's environment.

Usage:
  ros2 run warehouse_aggregator mock_publisher
  # or directly:
  python3 mock_publisher.py
"""

import math
import random
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String
from geometry_msgs.msg import Quaternion


ROBOT_IDS = [
  "3f8a1b2c-4d5e-6f7a-8b9c-0d1e2f3a4b5c",
  "7e6d5c4b-3a2f-1e0d-9c8b-7a6f5e4d3c2b",
]


def yaw_to_quaternion(yaw: float) -> Quaternion:
  q = Quaternion()
  q.z = math.sin(yaw / 2.0)
  q.w = math.cos(yaw / 2.0)
  return q


class MockRobotPublisher(Node):
  """
  Publishes mock telemetry for all robots at fixed intervals.

  Topics published per robot:
  - /{robot_id}/battery_state     (sensor_msgs/BatteryState)
  - /{robot_id}/odom              (nav_msgs/Odometry)
  - /{robot_id}/nav_status        (std_msgs/String)
  - /{robot_id}/operational_status (std_msgs/String)
  - /{robot_id}/heartbeat         (std_msgs/String)
  """

  def __init__(self):
    super().__init__("mock_robot_publisher")

    self._pubs = {}
    self._tick = 0

    for robot_id in ROBOT_IDS:
      self._pubs[robot_id] = {
        "battery":    self.create_publisher(BatteryState, f"/{robot_id}/battery_state", 10),
        "odom":       self.create_publisher(Odometry,     f"/{robot_id}/odom", 10),
        "nav_status": self.create_publisher(String,       f"/{robot_id}/nav_status", 10),
        "op_status":  self.create_publisher(String,       f"/{robot_id}/operational_status", 10),
        "heartbeat":  self.create_publisher(String,       f"/{robot_id}/heartbeat", 10),
      }

    self.create_timer(1.0, self._publish_all)
    self.get_logger().info(f"MockRobotPublisher started for: {ROBOT_IDS}")

  def _publish_all(self) -> None:
    self._tick += 1
    for i, robot_id in enumerate(ROBOT_IDS):
      self._publish_robot(robot_id, offset=i * 5.0)

  def _publish_robot(self, robot_id: str, offset: float) -> None:
    pubs = self._pubs[robot_id]
    t = self._tick

    # ── Battery ──────────────────────────────────
    bat = BatteryState()
    # Slowly drain battery to trigger events (starts ~80%, drains over time)
    bat.percentage = max(0.0, 0.80 - (t * 0.005))
    pubs["battery"].publish(bat)

    # ── Odometry ─────────────────────────────────
    odom = Odometry()
    odom.pose.pose.position.x = offset + math.sin(t * 0.1) * 3.0
    odom.pose.pose.position.y = offset + math.cos(t * 0.1) * 3.0
    odom.pose.pose.orientation = yaw_to_quaternion(t * 0.1)
    pubs["odom"].publish(odom)

    # ── Nav status ───────────────────────────────
    # Cycle through statuses to test event detection
    nav_statuses = ["NAVIGATING", "NAVIGATING", "NAVIGATING", "BLOCKED", "SUCCEEDED"]
    nav_msg = String()
    nav_msg.data = nav_statuses[t % len(nav_statuses)]
    pubs["nav_status"].publish(nav_msg)

    # ── Operational status ────────────────────────
    op_statuses = ["BUSY", "BUSY", "BUSY", "IDLE", "BUSY"]
    op_msg = String()
    op_msg.data = op_statuses[t % len(op_statuses)]
    pubs["op_status"].publish(op_msg)

    # ── Heartbeat ─────────────────────────────────
    hb = String()
    hb.data = "ping"
    pubs["heartbeat"].publish(hb)


def main(args=None):
  rclpy.init(args=args)
  node = MockRobotPublisher()
  try:
    rclpy.spin(node)
  except KeyboardInterrupt:
    pass
  finally:
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
  main()
