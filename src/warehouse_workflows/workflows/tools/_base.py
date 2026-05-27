"""
Tool layer base types.

ToolReceipt is the structured return value every tool function returns.
Workflows read command_id from it to populate commands_issued, and call
to_dict() to embed the receipt in the audit decisions log.

Priority policy is owned here — callers express urgency, not numbers.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

Urgency = Literal["critical", "recovery", "normal", "scheduled"]

# Priority integers sent to the ROS executor via agent_commands.priority.
# These are the only place where urgency maps to a number in the codebase.
URGENCY_PRIORITY: dict[Urgency, int] = {
    "critical":  10,  # battery_critical, emergency stop
    "recovery":   8,  # path_blocked reroute
    "normal":     5,  # standard task dispatch
    "scheduled":  3,  # battery_low finish-first, low-priority nav
}

PAUSE_PRIORITY = 20  # pause_robot is always highest — safety invariant


@dataclass
class ToolReceipt:
    tool: str
    accepted: bool
    command_id: Optional[str] = None      # set when an agent_command was persisted
    rejection_reason: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out: dict = {"tool": self.tool, "accepted": self.accepted}
        if self.command_id:
            out["command_id"] = self.command_id
        if not self.accepted:
            out["rejection_reason"] = self.rejection_reason
        out.update(self.meta)
        return out
