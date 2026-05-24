import asyncio
import logging
import threading
from datetime import datetime
from typing import Dict

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String

from aggregator.schemas.models import RobotState
from aggregator.cache.state_cache import StateCache
from aggregator.db.db_writer import DBWriter
from aggregator.event_detector import EventDetector
from aggregator.monitors.battery_monitor import BatteryMonitor
from aggregator.monitors.navigation_monitor import NavigationMonitor
from aggregator.semantics.operational_semantics import OPERATIONAL_STATUS_MAP

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Configuration
# Extend ROBOT_IDS as more robots are added
# ─────────────────────────────────────────────

ROBOT_IDS = [
  "robot_01",
  "robot_02",
]

#DB_DSN = "postgresql://user:password@localhost:5432/warehouse"
DB_DSN = "postgresql://songhwa:csh110427dg93@localhost:5432/warehouse"


class AggregatorNode(Node):
  """
  Central ROS2 node for the Context Aggregator.

  Responsibilities:
  - subscribe to all robot ROS2 topics
  - delegate raw message handling to per-robot monitors
  - merge partial state updates into the state cache
  - detect semantic events via EventDetector
  - persist state and events to PostgreSQL via DBWriter

  Does NOT:
  - plan or reason
  - call LLMs
  - execute robot commands
  - contain orchestration logic
  """

  def __init__(self):
    super().__init__("warehouse_aggregator")
    self.get_logger().info("AggregatorNode starting...")

    # ─── Shared infrastructure ───
    self._cache = StateCache()
    self._db = DBWriter(dsn=DB_DSN)
    self._detector = EventDetector(cache=self._cache)

    # ─── Async event loop in background thread ───
    # ROS2 callbacks are sync; DB writes are async.
    # We run an asyncio loop on a separate thread to avoid blocking.
    self._loop = asyncio.new_event_loop()
    self._loop_thread = threading.Thread(
      target=self._loop.run_forever,
      daemon=True,
      name="aggregator_async",
    )
    self._loop_thread.start()

    # Connect DB (blocks until pool is ready)
    future = asyncio.run_coroutine_threadsafe(self._db.connect(), self._loop)
    future.result(timeout=10)

    # ─── Per-robot monitors and subscriptions ───
    self._battery_monitors: Dict[str, BatteryMonitor] = {}
    self._nav_monitors: Dict[str, NavigationMonitor] = {}

    for robot_id in ROBOT_IDS:
      self._register_robot(robot_id)

    self.get_logger().info(f"AggregatorNode ready. Monitoring: {ROBOT_IDS}")

  # ─────────────────────────────────────────────
  # Robot Registration
  # ─────────────────────────────────────────────

  def _register_robot(self, robot_id: str) -> None:
    """
    Create monitors and subscribe to all topics for a robot.
    Topic convention: /{robot_id}/{topic}
    """

    # Battery monitor
    battery_mon = BatteryMonitor(
      robot_id=robot_id,
      on_state_update=self._on_partial_state,
    )
    self._battery_monitors[robot_id] = battery_mon

    self.create_subscription(
      BatteryState,
      f"/{robot_id}/battery_state",
      battery_mon.handle_battery_state,
      qos_profile=10,
    )

    # Navigation monitor — odometry
    nav_mon = NavigationMonitor(
      robot_id=robot_id,
      on_state_update=self._on_partial_state,
    )
    self._nav_monitors[robot_id] = nav_mon

    self.create_subscription(
      Odometry,
      f"/{robot_id}/odom",
      nav_mon.handle_odom,
      qos_profile=10,
    )

    # Navigation monitor — status string
    self.create_subscription(
      String,
      f"/{robot_id}/nav_status",
      nav_mon.handle_nav_status,
      qos_profile=10,
    )

    # Operational status
    self.create_subscription(
      String,
      f"/{robot_id}/operational_status",
      lambda msg, rid=robot_id: self._handle_operational_status(rid, msg),
      qos_profile=10,
    )

    # Heartbeat
    self.create_subscription(
      String,
      f"/{robot_id}/heartbeat",
      lambda msg, rid=robot_id: self._handle_heartbeat(rid, msg),
      qos_profile=10,
    )

    logger.info(f"Registered subscriptions for {robot_id}")

  # ─────────────────────────────────────────────
  # Operational Status Handler
  # ─────────────────────────────────────────────

  def _handle_operational_status(self, robot_id: str, msg: String) -> None:
    raw = msg.data.strip().upper()
    semantic = OPERATIONAL_STATUS_MAP.get(raw)
    if semantic:
      self._on_partial_state(RobotState(
        robot_id=robot_id,
        operational_status=semantic,
      ))

  # ─────────────────────────────────────────────
  # Heartbeat Handler
  # ─────────────────────────────────────────────

  def _handle_heartbeat(self, robot_id: str, msg: String) -> None:
    self._on_partial_state(RobotState(
      robot_id=robot_id,
      last_heartbeat=datetime.utcnow(),
    ))

  # ─────────────────────────────────────────────
  # State Merge + Persist Pipeline
  # ─────────────────────────────────────────────

  def _on_partial_state(self, partial: RobotState) -> None:
    """
    Called by every monitor with a partial RobotState update.

    Pipeline:
    1. Merge partial fields into cached full state
    2. Detect events from the transition
    3. Persist updated state to PostgreSQL
    4. Persist any new events to PostgreSQL
    """
    merged = self._cache.merge_and_set(partial) # atomic
    events = self._detector.detect(merged) # uses snapshot, not live cache
    
    for event in events:
      logger.info(f"Event: {event.event_type} | robot: {event.robot_id}")
      asyncio.run_coroutine_threadsafe(
        self._db.insert_event(event),
        self._loop,
      )
    
    # Async DB writes (non-blocking)
    asyncio.run_coroutine_threadsafe(
      self._db.upsert_robot_state(merged),
      self._loop,
    )


  '''
  def _merge_state(self, partial: RobotState) -> RobotState:
    """
    Merge partial state fields into the existing cached state.
    Fields set to None in the partial update are preserved from cache.
    """
    cached = self._cache.get(partial.robot_id)

    if cached is None:
      # First time seeing this robot
      return partial

    # Merge: prefer partial's non-None values, fall back to cached
    def pick(new_val, cached_val):
      return new_val if new_val is not None else cached_val

    return RobotState(
      robot_id=partial.robot_id,
      robot_name=         pick(partial.robot_name,          cached.robot_name),
      x=                  pick(partial.x,                   cached.x),
      y=                  pick(partial.y,                   cached.y),
      theta=              pick(partial.theta,                cached.theta),
      current_zone=       pick(partial.current_zone,        cached.current_zone),
      battery_pct=        pick(partial.battery_pct,         cached.battery_pct),
      operational_status= pick(partial.operational_status,  cached.operational_status),
      navigation_status=  pick(partial.navigation_status,   cached.navigation_status),
      current_mission_id= pick(partial.current_mission_id,  cached.current_mission_id),
      current_task_id=    pick(partial.current_task_id,     cached.current_task_id),
      last_heartbeat=     pick(partial.last_heartbeat,      cached.last_heartbeat),
      health_score=       pick(partial.health_score,        cached.health_score),
    )
  '''

  # ─────────────────────────────────────────────
  # Shutdown
  # ─────────────────────────────────────────────

  def destroy_node(self) -> None:
    future = asyncio.run_coroutine_threadsafe(self._db.close(), self._loop)
    future.result(timeout=5)
    self._loop.call_soon_threadsafe(self._loop.stop)
    super().destroy_node()


# ─────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────

def main(args=None):
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
  )

  rclpy.init(args=args)
  node = AggregatorNode()

  try:
    rclpy.spin(node)
  except KeyboardInterrupt:
    pass
  finally:
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
  main()
