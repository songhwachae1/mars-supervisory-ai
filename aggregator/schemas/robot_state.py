from pydantic import BaseModel, Field

from datetime import datetime
from uuid import UUID

from typing import Optional


# ─────────────────────────────────────────────
# Robot State
# Maps to: robot_state table
# ─────────────────────────────────────────────
 
class RobotState(BaseModel):

	robot_id: UUID

	robot_name: Optional[str] = None

	# position
	x: float = 0.0
	y: float = 0.0
	theta: float = 0.0

	current_zone: Optional[str] = None

	battery_pct: float = 100.0

	# status
	# idle | busy | charging | error
	operational_status: str = "idle"

	# navigating | path_blocked | arrived | failed
	navigation_status: str = "arrived"

	current_mission_id: Optional[UUID] = None

	current_task_id: Optional[UUID] = None

	last_heartbeat: Optional[datetime] = None

	health_score: float = 1.0

	metadata: dict = Field(default_factory=dict)

	updated_at: datetime