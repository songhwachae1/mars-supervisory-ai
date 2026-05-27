"""
Robot control tools.

pause_robot — intent: immediately halt all motion on a robot.

Priority is fixed at the safety ceiling (20) and is not caller-configurable.
"""

import asyncpg

from workflows import db
from workflows.tools._base import PAUSE_PRIORITY, ToolReceipt


async def pause_robot(
    pool: asyncpg.Pool,
    *,
    robot_id: str,
    reason: str,
    issued_by: str = "tool_layer",
) -> ToolReceipt:
    """Halt robot_id. Always issues at maximum priority."""
    command_id = await db.insert_agent_command(
        pool,
        robot_id=robot_id,
        source_agent=issued_by,
        command_type="pause_robot",
        payload={"reason": reason},
        priority=PAUSE_PRIORITY,
    )
    return ToolReceipt(
        tool="pause_robot",
        accepted=True,
        command_id=command_id,
        meta={"reason": reason},
    )
