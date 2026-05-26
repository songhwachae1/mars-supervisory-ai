"""
Event Router

A deterministic, orchestration-only daemon that:

  1. Reads unprocessed events from PostgreSQL
  2. Locks events to prevent duplicate execution
  3. Selects a workflow deterministically from a static map
  4. Builds workflow input state from the event + blackboard
  5. Launches the LangGraph workflow            (← TODO)
  6. Tracks execution state via workflow_execution
  7. Marks the event processed

This module is NOT an AI agent. It does not:

  - run prompts
  - call LLMs
  - plan
  - delegate autonomously
  - hit vector memory
  - touch ROS

It only routes.
"""

from event_router.router import EventRouter
from event_router.models import ClaimedEvent, WorkflowInput
