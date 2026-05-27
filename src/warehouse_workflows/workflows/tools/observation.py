"""
Observation and escalation tools.

record_anomaly        — persist a structured anomaly record.
                        Used for health events, blockages, and errors
                        that need to be surfaced to agents or operators.

flag_for_intervention — escalate to human review by inserting a
                        needs_human_intervention anomaly record.
"""

from typing import Optional

import asyncpg

from workflows import db
from workflows.tools._base import ToolReceipt


async def record_anomaly(
    pool: asyncpg.Pool,
    *,
    robot_id: str,
    anomaly_type: str,
    severity: str,
    detected_by: str,
    related_event_id: Optional[int],
    description: str,
    state_snapshot: Optional[dict] = None,
) -> ToolReceipt:
    anomaly_id = await db.insert_anomaly(
        pool,
        robot_id=robot_id,
        anomaly_type=anomaly_type,
        severity=severity,
        detected_by=detected_by,
        related_event_id=related_event_id,
        description=description,
        state_snapshot=state_snapshot,
    )
    return ToolReceipt(
        tool="record_anomaly",
        accepted=True,
        meta={"anomaly_id": anomaly_id},
    )


async def flag_for_intervention(
    pool: asyncpg.Pool,
    *,
    robot_id: str,
    related_event_id: Optional[int],
    description: str,
    state_snapshot: Optional[dict] = None,
) -> ToolReceipt:
    """
    Insert a needs_human_intervention anomaly so operator dashboards
    can surface it. Severity is always critical.
    """
    anomaly_id = await db.insert_anomaly(
        pool,
        robot_id=robot_id,
        anomaly_type="needs_human_intervention",
        severity="critical",
        detected_by="tool_layer",
        related_event_id=related_event_id,
        description=description,
        state_snapshot=state_snapshot,
    )
    return ToolReceipt(
        tool="flag_for_intervention",
        accepted=True,
        meta={"anomaly_id": anomaly_id},
    )
