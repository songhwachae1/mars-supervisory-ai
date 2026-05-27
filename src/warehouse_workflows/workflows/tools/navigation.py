"""
Navigation tools.

navigate_to — intent: move a robot to a named warehouse location.

Validates the destination exists, resolves coordinates internally,
applies the urgency→priority policy, persists an agent_command, and
returns a ToolReceipt.  Callers express *what* they want; this layer
decides *how* to represent it as a safe, validated command.
"""

import asyncpg

from workflows import db
from workflows.tools._base import URGENCY_PRIORITY, Urgency, ToolReceipt


async def navigate_to(
    pool: asyncpg.Pool,
    *,
    robot_id: str,
    destination_shelf_id: str,
    reason: str,
    urgency: Urgency = "scheduled",
    recovery_attempt: int = 0,
    issued_by: str = "tool_layer",
) -> ToolReceipt:
    """
    Move robot_id to destination_shelf_id.

    Rejects if the shelf is not in warehouse_locations — callers should
    not need to pre-validate coordinates; that is this layer's job.
    """
    dest = await db.find_location(pool, destination_shelf_id)
    if dest is None:
        return ToolReceipt(
            tool="navigate_to",
            accepted=False,
            rejection_reason=f"unknown_destination:{destination_shelf_id}",
        )

    command_id = await db.insert_agent_command(
        pool,
        robot_id=robot_id,
        source_agent=issued_by,
        command_type="navigate_to",
        payload={
            "destination_shelf_id": destination_shelf_id,
            "x":                    dest["x"],
            "y":                    dest["y"],
            "reason":               reason,
            "recovery_attempt":     recovery_attempt,
        },
        priority=URGENCY_PRIORITY[urgency],
    )
    return ToolReceipt(
        tool="navigate_to",
        accepted=True,
        command_id=command_id,
        meta={
            "destination_shelf_id": destination_shelf_id,
            "urgency":              urgency,
            "recovery_attempt":     recovery_attempt,
        },
    )
