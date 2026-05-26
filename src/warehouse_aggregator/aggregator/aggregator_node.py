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
from aggregator import config
from aggregator.db.db_writer import DBWriter
from aggregator.monitors.battery_monitor import BatteryMonitor
from aggregator.monitors.navigation_monitor import NavigationMonitor
from aggregator.semantics.operational_semantics import OPERATIONAL_STATUS_MAP

from event_system import EventPipeline

logger = logging.getLogger(__name__)


# Extend ROBOT_IDS as more robots are added.
ROBOT_IDS = [
  "robot_01",
  "robot_02",
]


class AggregatorNode(Node):
  """
  Central ROS2 node for the Context Aggregator.

  Responsibilities:
  - subscribe to all robot ROS2 topics
  - delegate raw message handling to per-robot monitors
  - merge partial state updates into the state cache
  - persist robot state to PostgreSQL via DBWriter
  - hand state transitions to the event_system pipeline

  Does NOT:
  - plan or reason
  - call LLMs
  - execute robot commands
  - contain orchestration logic
  - own event detection or persistence (that's the event_system's job)
  """

  def __init__(self):
    super().__init__("warehouse_aggregator")
    self.get_logger().info("AggregatorNode starting...")

    # ─── Shared infrastructure ───
    self._cache = StateCache()
    self._db = DBWriter(dsn=config.DB_DSN)

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

    # ─── Event pipeline ───
    # Shares the asyncpg pool with DBWriter so we don't open two pools.
    self._pipeline = EventPipeline.build_default(self._db.pool)
    # Background sweeper for orchestrator-timeout cleanup.
    asyncio.run_coroutine_threadsafe(
      self._start_pipeline_expiry(),
      self._loop,
    )

    # ─── Per-robot monitors and subscriptions ───
    self._battery_monitors: Dict[str, BatteryMonitor] = {}
    self._nav_monitors: Dict[str, NavigationMonitor] = {}

    for robot_id in ROBOT_IDS:
      self._register_robot(robot_id)

    self.get_logger().info(f"AggregatorNode ready. Monitoring: {ROBOT_IDS}")

  async def _start_pipeline_expiry(self) -> None:
    # Must be called from within the async loop so asyncio.create_task
    # binds to the right loop.
    self._pipeline.start_expiry_loop(ttl_seconds=60, interval_seconds=30)

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
    1. Merge partial fields into cached full state (atomic; returns prev + merged)
    2. Persist updated state to PostgreSQL
    3. Hand the (prev, merged) transition to the event_system
    """
    prev, merged = self._cache.merge_and_set(partial)

    # Async DB write for the robot state row (non-blocking).
    asyncio.run_coroutine_threadsafe(
      self._db.upsert_robot_state(merged),
      self._loop,
    )

    # Hand the transition to the event_system. It owns detection,
    # construction, severity, dedup, persistence, and dispatch.
    asyncio.run_coroutine_threadsafe(
      self._pipeline.submit(prev, merged),
      self._loop,
    )

  # ─────────────────────────────────────────────
  # Shutdown
  # ─────────────────────────────────────────────

  def destroy_node(self) -> None:
    stop_future = asyncio.run_coroutine_threadsafe(self._pipeline.stop_expiry_loop(), self._loop)
    try:
      stop_future.result(timeout=5)
    except Exception:
      pass

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
