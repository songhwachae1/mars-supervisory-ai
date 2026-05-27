"""
Mission lifecycle tools.

pause_mission   — suspend an in-flight mission (robot will resume later).
resume_mission  — re-queue a paused mission as pending.
claim_mission   — atomically assign the highest-priority pending mission
                  to a robot. Returns the mission in receipt.meta["mission"];
                  None means no mission was available (valid, not a failure).
"""

import asyncpg

from workflows import db
from workflows.tools._base import ToolReceipt


async def pause_mission(
    pool: asyncpg.Pool,
    *,
    mission_id: str,
    reason: str,
) -> ToolReceipt:
    if not mission_id:
        return ToolReceipt(
            tool="pause_mission",
            accepted=False,
            rejection_reason="missing_mission_id",
        )
    await db.update_mission_status(pool, mission_id, "paused")
    return ToolReceipt(
        tool="pause_mission",
        accepted=True,
        meta={"mission_id": mission_id, "reason": reason},
    )


async def resume_mission(
    pool: asyncpg.Pool,
    *,
    mission_id: str,
) -> ToolReceipt:
    if not mission_id:
        return ToolReceipt(
            tool="resume_mission",
            accepted=False,
            rejection_reason="missing_mission_id",
        )
    await db.update_mission_status(pool, mission_id, "pending")
    return ToolReceipt(
        tool="resume_mission",
        accepted=True,
        meta={"mission_id": mission_id},
    )


async def claim_mission(
    pool: asyncpg.Pool,
    *,
    robot_id: str,
) -> ToolReceipt:
    """
    Atomically find and assign a pending mission to robot_id.

    Uses FOR UPDATE SKIP LOCKED internally so concurrent claims for
    different robots cannot grab the same mission.
    """
    mission = await db.claim_pending_mission(pool, robot_id)
    return ToolReceipt(
        tool="claim_mission",
        accepted=True,
        meta={"mission": mission},  # None when no pending mission exists
    )
