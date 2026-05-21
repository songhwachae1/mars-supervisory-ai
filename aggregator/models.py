from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import uuid


# ─────────────────────────────────────────────
# Robot State
# Maps to: robot_state table
# ─────────────────────────────────────────────

@dataclass
class RobotState:
  robot_id: str
  robot_name: Optional[str] = None

  # position
  x: Optional[float] = None
  y: Optional[float] = None
  theta: Optional[float] = None
  current_zone: Optional[str] = None

  # health
  battery_pct: Optional[float] = None
  health_score: float = 1.0

  # status
  operational_status: Optional[str] = None   # idle | busy | charging | error
  navigation_status: Optional[str] = None    # navigating | path_blocked | arrived | failed

  # mission linkage
  current_mission_id: Optional[str] = None
  current_task_id: Optional[str] = None

  last_heartbeat: Optional[datetime] = None
  updated_at: datetime = field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────
# Robot Event
# Maps to: robot_events table
# ─────────────────────────────────────────────

@dataclass
class RobotEvent:
  robot_id: str
  event_type: str                             # battery_low | path_blocked | human_detected | ...
  severity: Optional[str] = None             # info | warning | critical
  source_component: Optional[str] = None     # battery_monitor | navigation_monitor | ...
  payload: dict = field(default_factory=dict)
  created_at: datetime = field(default_factory=datetime.utcnow)
