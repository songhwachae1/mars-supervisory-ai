"""
Task lifecycle tools.

dispatch_task   — activate a task AND issue a start_task agent_command.
                  Used by the scheduler when kicking off the first task
                  of a newly claimed mission.

activate_task   — mark a task active in the DB without issuing a command.
                  Used by task_completion_workflow when advancing to the
                  next task mid-mission (executor is already running).

complete_task   — mark a task as done.
complete_mission — mark a mission as done (no tasks remain).
"""

from typing import Optional

import asyncpg

from workflows import db
from workflows.tools._base import ToolReceipt


async def dispatch_task(
    pool: asyncpg.Pool,
    *,
    task_id: str,
    robot_id: str,
    mission_id: str,
    task_type: Optional[str],
    priority: int = 0,
    issued_by: str = "tool_layer",
) -> ToolReceipt:
    """Activate task and issue a start_task command to the executor."""
    await db.activate_task(pool, task_id)
    command_id = await db.insert_agent_command(
        pool,
        robot_id=robot_id,
        source_agent=issued_by,
        command_type="start_task",
        payload={
            "task_id":    task_id,
            "task_type":  task_type,
            "mission_id": mission_id,
        },
        priority=priority,
        mission_id=mission_id,
    )
    return ToolReceipt(
        tool="dispatch_task",
        accepted=True,
        command_id=command_id,
        meta={"task_id": task_id, "mission_id": mission_id},
    )


async def activate_task(
    pool: asyncpg.Pool,
    *,
    task_id: str,
) -> ToolReceipt:
    """Transition task to active state. No command issued."""
    await db.activate_task(pool, task_id)
    return ToolReceipt(
        tool="activate_task",
        accepted=True,
        meta={"task_id": task_id},
    )


async def complete_task(
    pool: asyncpg.Pool,
    *,
    task_id: str,
) -> ToolReceipt:
    await db.complete_task(pool, task_id)
    return ToolReceipt(
        tool="complete_task",
        accepted=True,
        meta={"task_id": task_id},
    )


async def complete_mission(
    pool: asyncpg.Pool,
    *,
    mission_id: str,
) -> ToolReceipt:
    await db.complete_mission(pool, mission_id)
    return ToolReceipt(
        tool="complete_mission",
        accepted=True,
        meta={"mission_id": mission_id},
    )
