from pydantic import BaseModel


class RobotState(BaseModel):
	robot_id: str

	x: float = 0.0
	y: float = 0.0
  
	battery_pct: float = 100.0

  status: str = "idle"

  updated_at: datetime