# ROS 2 + LangGraph Blackboard Architecture Design

## Overview

This document describes the architecture for a multi-agent robotic orchestration system built using:

- ROS 2
- PostgreSQL
- LangGraph / LangChain
- Context Aggregation Layer
- Blackboard / Shared Memory Architecture
- Event-Driven Workflow Triggers

The system is designed for:

- Multi-robot orchestration
- Persistent shared world state
- LLM-driven reasoning and planning
- Durable workflow execution
- Recovery and rollback support
- Modular sub-agent coordination
- Semantic robotics state management

---

# High-Level Architecture

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

Event-driven workflow activation:

```text
Events
 ↓
Trigger LangGraph workflows
```

---

# Core Architectural Principles

## 1. ROS Owns Realtime Robotics

ROS 2 is responsible for:

- Sensor communication
- Navigation
- Motor control
- Hardware drivers
- Realtime robotics loops
- Safety systems
- Action execution

The LLM layer must never directly control motors or realtime robotics loops.

---

## 2. PostgreSQL Is the Shared World Model

PostgreSQL acts as:

- Blackboard memory
- Shared semantic state
- Persistent workflow state
- Agent coordination layer
- Task tracking system
- Event store
- Audit log
- Replay/debugging source

---

## 3. Context Aggregator Performs Semantic Translation

The Context Aggregator converts:

```text
Raw ROS Telemetry
        ↓
Semantic Structured State
```

Example:

| Raw ROS Data | Semantic State |
|---|---|
| battery_voltage=10.7 | battery_low |
| navigation_status=blocked | path_blocked |
| object_detection=human | human_detected |

The aggregator should NOT:

- perform planning
- contain orchestration logic
- perform LLM reasoning
- execute workflows

Its responsibility is strictly semantic normalization and event extraction.

---

## 4. LangGraph Owns Orchestration

LangGraph is responsible for:

- Workflow execution
- Agent coordination
- Task planning
- Recovery workflows
- Retry policies
- Human approval checkpoints
- Delegation to sub-agents
- Tool execution routing

---

# System Components

# 1. ROS Nodes

## Responsibilities

ROS nodes handle:

- Sensor acquisition
- Navigation stack
- Localization
- Mapping
- Manipulation
- Motor control
- Safety systems
- Realtime execution

## Example Nodes

```text
Camera Node
Lidar Node
Navigation Node
Localization Node
Battery Monitor Node
Motor Controller Node
Manipulation Node
```

## ROS Communication Mechanisms

- Topics
- Services
- Actions
- TF
- Parameters

---

# 2. Context Aggregator

## Responsibilities

The Context Aggregator:

- subscribes to ROS topics
- filters noisy telemetry
- extracts semantic state
- generates events
- updates blackboard state
- rate limits updates
- tracks state transitions

---


## Example Semantic Transformations

### Battery Example

Raw ROS:

```text
battery_voltage = 10.7
```

Semantic Output:

```json
{
  "battery_status": "low"
}
```

---

### Navigation Example

Raw ROS:

```text
nav_status = blocked
```

Semantic Output:

```json
{
  "status": "path_blocked"
}
```

---

## Aggregator Design Rules

### Responsibilities

- semantic summarization
- event extraction
- normalization
- filtering
- state persistence
- timestamping

---

## State vs Events

### State

Represents current truth.

Example:

```json
{
  "robot_id": "robot_1",
  "location": "hallway",
  "battery": 18,
  "status": "idle"
}
```

### Events

Represents something that happened.

Example:

```json
{
  "event_type": "path_blocked",
  "robot_id": "robot_1"
}
```

Both are required.

---

# 3. PostgreSQL Blackboard

## Responsibilities

The PostgreSQL blackboard acts as:

- shared memory
- semantic world model
- persistent coordination layer
- orchestration state store
- event store
- task tracking system

---

# 4. Event System

## Purpose

Events trigger workflows only when meaningful state changes occur.

This reduces:

- token usage
- unnecessary orchestration cycles
- redundant LLM reasoning

---

## Example Events

```text
battery_low
path_blocked
human_detected
navigation_failed
robot_idle
emergency_stop
mission_completed
```

---

## Event Flow

```text
ROS State
   ↓
Context Aggregator
   ↓
Event Detection
   ↓
PostgreSQL Event Store
   ↓
LangGraph Trigger
```

---

# 5. LangGraph Orchestrator

## Responsibilities

The orchestrator:

- reads blackboard state
- reacts to events
- plans workflows
- delegates tasks
- coordinates sub-agents
- performs recovery handling
- tracks execution state
- writes commands

---


## Example Workflow

```text
path_blocked event
        ↓
Recovery Workflow
        ↓
Recovery Agent
        ↓
Generate reroute command
        ↓
Write command to blackboard
```

---

# 6. Sub Agents

## Responsibilities

Sub-agents specialize in narrow domains.

Examples:

| Agent | Responsibility |
|---|---|
| Navigation Agent | route planning |
| Recovery Agent | failure handling |
| Monitoring Agent | system health |
| Scheduling Agent | task allocation |
| Manipulation Agent | arm/gripper workflows |

---

## Important Design Principle

Sub-agents should:

- reason semantically
- call tools
- avoid direct ROS control

---

# 7. Tool Calling Layer

## Purpose

The tool layer exposes safe executable capabilities.

Example tools:

```
move_to(location)
retry_navigation(task_id)
pause_robot(robot_id)
resume_workflow(workflow_id)
return_to_charger(robot_id)
```

---

## Benefits

Tool abstraction:

- constrains LLM behavior
- improves safety
- standardizes execution
- simplifies orchestration

---

# 8. ROS Executors

## Responsibilities

ROS Executors:

- read commands from PostgreSQL
- translate commands into ROS actions/services/topics
- monitor execution
- report results
- update task state

---

## Example Execution Flow

```text
agent_command
      ↓
ROS Executor
      ↓
Navigation Action
      ↓
Robot Movement
      ↓
Execution Result
      ↓
PostgreSQL Update
```

---

# End-to-End Workflow Example

# Scenario: Path Blocked

## Step 1 — ROS Detects Failure

```text
Navigation node reports blocked path
```

---

## Step 2 — Aggregator Creates Semantic Event

```json
{
  "event_type": "path_blocked",
  "robot_id": "robot_1"
}
```

---

## Step 3 — Event Stored in PostgreSQL

```text
robot_events table updated
```

---

## Step 4 — LangGraph Workflow Triggered

```text
Recovery workflow activated
```

---

## Step 5 — Recovery Agent Plans Response

Example:

```json
{
  "action": "reroute",
  "destination": "hallway_b"
}
```

---

## Step 6 — Command Written to Blackboard

```text
agent_commands updated
```

---

## Step 7 — ROS Executor Executes Action

```text
Navigation action sent to robot
```

---

## Step 8 — Result Persisted

```text
task completed
robot_state updated
```

---

# Technology Stack

| Layer | Technology |
|---|---|
| Robotics Middleware | ROS 2 |
| Database | PostgreSQL |
| Orchestration | LangGraph |
| LLM Framework | LangChain |
| Aggregator Runtime | Python + rclpy |
| DB Access | asyncpg / psycopg |
| Containerization | Docker |
| Deployment | Kubernetes (optional) |

---

# Scalability Considerations

- semantic filtering
- event-driven activation
- state caching
- command validation
- checkpoint persistence
- workflow durability

---

# Security and Safety

## Safety Controls

- kill switch
- approval checkpoints
- command validation
- role-based permissions
- execution timeouts
- retry limits
- workflow rollback
- canary execution

---

# Future Extensions

Possible future additions:

- vector memory layer
- semantic world graph
- fleet optimization agents
- distributed event bus
- human-in-the-loop approvals
- simulation environments
- reinforcement learning integration
- predictive maintenance agents

---

# Final Architectural Guidance

The most important architectural principle is:

```text
ROS handles realtime robotics.
LLMs handle semantic reasoning.
PostgreSQL coordinates shared state.
```

The Context Aggregator should remain:

```text
small
predictable
semantic
non-agentic
```

This separation keeps the system:

- scalable
- debuggable
- maintainable
- safe
- orchestration-friendly
- multi-robot capable

