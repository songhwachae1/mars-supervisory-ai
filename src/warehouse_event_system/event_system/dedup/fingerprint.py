"""
Deduplication fingerprint.

The fingerprint collapses logically-identical events into one workflow.
A robot reporting "path_blocked" ten times in two seconds must fire only
one workflow — so the fingerprint is intentionally coarse:

    (robot_id, event_type)

We deliberately do NOT include the payload — two `path_blocked` events
with slightly different (x, y) coordinates are still "the same problem"
from an orchestration standpoint. If a more granular dedup is ever
needed (e.g. per-zone), extend this function.
"""

from event_system.schemas.models import Event


def fingerprint(event: Event) -> str:
  return f"{event.robot_id}:{event.event_type}"
