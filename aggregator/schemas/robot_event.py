from pydantic import BaseModel, Field

from datetime import datetime
from uuid import UUID

from typing import Optional


# ─────────────────────────────────────────────
# Robot Event
# Maps to: robot_events table
# ─────────────────────────────────────────────

class RobotEvent(BaseModel):

    id: Optional[int] = None

    robot_id: Optional[UUID] = None

    event_type: str

    severity: Optional[str] = None

    source_component: Optional[str] = None

    payload: dict = Field(default_factory=dict)

    processed: bool = False

    created_at: Optional[datetime] = None