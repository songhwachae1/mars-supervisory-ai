# Multi-Agent ROS 2 Orchestration System

## Overview

This project is a multi-agent robotic orchestration platform built using:

- ROS 2
- PostgreSQL Blackboard Architecture
- LangGraph
- LangChain
- Event-Driven Workflow Execution
- Tool-Based Agent Execution

The system enables:

- Multi-robot coordination
- Persistent shared world state
- Semantic context aggregation
- LLM-driven task planning
- Durable workflow orchestration
- Recovery and rollback workflows
- Event-triggered execution
- Safe robotic action execution

---

# Architecture

```text
ROS Nodes
    ↓
Context Aggregator
    ↓
PostgreSQL Blackboard
    ↓
LangGraph Orchestrator
    ↓
Sub Agents
    ↓
Tool Calls
    ↓
ROS Executors
```

Event-driven activation:

```text
Events
 ↓
Trigger LangGraph workflows
```

---

# Core Concepts

## ROS 2

ROS 2 handles:

- realtime robotics communication
- navigation
- sensors
- motor control
- hardware interfaces
- robot execution

---

## Context Aggregator

The Context Aggregator converts:

```text
Raw ROS telemetry
        ↓
Semantic structured context
```

Example:

| Raw ROS Data | Semantic Context |
|---|---|
| battery_voltage=10.7 | battery_low |
| nav_status=blocked | path_blocked |
| object_detection=person | human_detected |

The aggregator writes semantic state and events into PostgreSQL.

---

## PostgreSQL Blackboard

PostgreSQL acts as:

- shared memory layer
- world model
- task state store
- event store
- workflow persistence layer
- orchestration memory
- audit/replay system

---

## LangGraph Orchestrator

The orchestrator:

- reacts to events
- coordinates workflows
- delegates tasks to sub-agents
- performs recovery handling
- manages checkpoints
- controls workflow execution

---

## Sub Agents

Specialized agents handle narrow responsibilities.

Examples:

| Agent | Responsibility |
|---|---|
| Navigation Agent | route planning |
| Recovery Agent | failure handling |
| Scheduling Agent | task allocation |
| Monitoring Agent | health monitoring |
| Manipulation Agent | arm/gripper workflows |

---

## Tool Calling Layer

Agents interact with the robot system through tools.

Example:

```python
move_to(location)
pause_robot(robot_id)
retry_navigation(task_id)
return_to_charger(robot_id)
```

---

## ROS Executors

ROS Executors:

- consume commands
- translate commands into ROS actions/services/topics
- monitor execution
- update execution results

---

# Repository Structure

```text
project-root/
│
├── README.md
├── docker-compose.yml
├── .env
├── requirements.txt
│
├── docs/
│   ├── architecture.md
│   ├── workflows.md
│   ├── database_schema.md
│   └── event_system.md
│
├── aggregator/
│   ├── aggregator_node.py
│   ├── battery_monitor.py
│   ├── navigation_monitor.py
│   ├── event_detector.py
│   ├── db_writer.py
│   ├── state_cache.py
│   └── schemas/
│
├── orchestrator/
│   ├── graph.py
│   ├── state.py
│   ├── event_router.py
│   ├── workflow_manager.py
│   ├── checkpoint_manager.py
│   ├── recovery_manager.py
│   └── agents/
│       ├── navigation_agent.py
│       ├── recovery_agent.py
│       ├── scheduling_agent.py
│       └── monitoring_agent.py
│
├── tools/
│   ├── navigation_tools.py
│   ├── robot_tools.py
│   ├── recovery_tools.py
│   └── validation_tools.py
│
├── executors/
│   ├── command_executor.py
│   ├── navigation_executor.py
│   ├── manipulation_executor.py
│   └── status_reporter.py
│
├── database/
│   ├── schema.sql
│   ├── migrations/
│   └── seed/
│
├── events/
│   ├── event_consumer.py
│   ├── event_dispatcher.py
│   └── triggers/
│
├── ros/
│   ├── launch/
│   ├── configs/
│   ├── nodes/
│   └── interfaces/
│
├── tests/
│   ├── integration/
│   ├── workflows/
│   └── agents/
│
└── scripts/
    ├── start_system.sh
    ├── reset_db.sh
    └── run_simulation.sh
```

---

# Data Flow

## High-Level Flow

```text
ROS Sensors
     ↓
ROS Nodes
     ↓
Context Aggregator
     ↓
PostgreSQL Blackboard
     ↓
Event Detection
     ↓
LangGraph Workflow
     ↓
Sub-Agent Reasoning
     ↓
Tool Calls
     ↓
ROS Executors
     ↓
Robot Actions
```

---

# Example Workflow

## Scenario: Robot Path Blocked

### Step 1

ROS navigation node reports:

```text
path blocked
```

---

### Step 2

Context Aggregator generates semantic event:

```json
{
  "event_type": "path_blocked",
  "robot_id": "robot_1"
}
```

---

### Step 3

Event stored in PostgreSQL.

---

### Step 4

LangGraph workflow triggered.

---

### Step 5

Recovery Agent generates reroute plan.

---

### Step 6

Tool call created:

```json
{
  "action": "reroute",
  "destination": "hallway_b"
}
```

---

### Step 7

ROS Executor converts command into ROS navigation action.

---

### Step 8

Robot executes reroute.

---

# Recommended Technology Stack

| Layer | Technology |
|---|---|
| Robotics Middleware | ROS 2 |
| Shared Memory | PostgreSQL |
| Orchestration | LangGraph |
| LLM Framework | LangChain |
| Aggregator Runtime | Python + rclpy |
| DB Driver | asyncpg / psycopg |
| Containerization | Docker |
| Deployment | Kubernetes (optional) |

---

# Database Tables

## robot_state

Stores latest semantic robot state.

## robot_events

Stores semantic event history.

## agent_commands

Stores orchestrator-generated commands.

## tasks

Tracks long-running workflows.

## workflow_checkpoints

Supports rollback and recovery.

---

# Event-Driven Workflows

The system uses event-driven execution to reduce unnecessary LLM calls.

Examples:

```text
battery_low
path_blocked
human_detected
navigation_failed
emergency_stop
mission_completed
```

Events trigger LangGraph workflows dynamically.

---

# Safety Features

Recommended safety mechanisms:

- kill switch
- retry limits
- execution timeouts
- workflow rollback
- checkpoint persistence
- command validation
- human approval checkpoints
- restricted tool access

---

# Design Principles

## 1. Keep ROS Realtime

Never route high-frequency robotics telemetry through LLM workflows.

---

## 2. Store Semantic State Only

Avoid storing:

- raw lidar streams
- image frames
- high-frequency IMU data
- raw TF trees

Instead store:

- semantic events
- summarized robot state
- workflow state
- task state

---

## 3. Keep Aggregator Thin

The Context Aggregator should NOT:

- perform planning
- contain orchestration logic
- execute workflows
- perform autonomous reasoning

Its job is semantic normalization only.

---

## 4. Use Tool-Based Execution

Agents should never directly manipulate ROS topics.

Use:

```text
Agent
  ↓
Tool Call
  ↓
Executor
  ↓
ROS Action
```

This improves:

- safety
- observability
- debugging
- validation
- rollback support

---

# Future Improvements

Possible future extensions:

- vector memory layer
- semantic world graph
- fleet optimization agents
- simulation environments
- reinforcement learning integration
- distributed event bus
- predictive maintenance workflows
- human-in-the-loop approvals

---

# Final Notes

This architecture separates responsibilities cleanly:

| Layer | Responsibility |
|---|---|
| ROS 2 | realtime robotics |
| Context Aggregator | semantic translation |
| PostgreSQL | shared world state |
| LangGraph | orchestration |
| Sub Agents | specialized reasoning |
| Tool Layer | safe execution abstraction |
| Executors | robot execution |

This separation makes the system:

- scalable
- modular
- observable
- maintainable
- multi-robot capable
- orchestration-friendly
- suitable for durable LLM workflows

