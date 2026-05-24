-- =====================================================
-- Multi-Agent ROS2 Orchestration Blackboard Schema
-- PostgreSQL + pgvector
-- =====================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =====================================================
-- WAREHOUSE LOCATIONS
-- =====================================================

CREATE TABLE IF NOT EXISTS warehouse_locations (
    id                  BIGSERIAL PRIMARY KEY,

    shelf_id            VARCHAR(20) UNIQUE NOT NULL,

    zone                VARCHAR(20) NOT NULL,

    x                   DOUBLE PRECISION NOT NULL,
    y                   DOUBLE PRECISION NOT NULL,
    z                   DOUBLE PRECISION DEFAULT 0,

    location_type       VARCHAR(30),

    metadata            JSONB DEFAULT '{}',

    updated_at          TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- INVENTORY ITEMS
-- =====================================================

CREATE TABLE IF NOT EXISTS inventory_items (
    id                  BIGSERIAL PRIMARY KEY,

    product_id          VARCHAR(50) UNIQUE NOT NULL,

    product_name        VARCHAR(200) NOT NULL,

    shelf_id            VARCHAR(20),

    quantity            INT DEFAULT 0,

    description         TEXT,

    metadata            JSONB DEFAULT '{}',

    embedding           vector(1536),

    updated_at          TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- ROBOT STATE
-- Current semantic robot state only
-- =====================================================

CREATE TABLE IF NOT EXISTS robot_state (
    robot_id            VARCHAR(50) PRIMARY KEY,

    robot_name          VARCHAR(50),

    x                   DOUBLE PRECISION,
    y                   DOUBLE PRECISION,
    theta               DOUBLE PRECISION,

    current_zone        VARCHAR(20),

    battery_pct         FLOAT,

    operational_status  VARCHAR(30),
    navigation_status   VARCHAR(30),

    current_mission_id  UUID,
    current_task_id     UUID,

    last_heartbeat      TIMESTAMP,

    health_score        FLOAT DEFAULT 1.0,

    metadata            JSONB DEFAULT '{}',

    updated_at          TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- ROBOT EVENTS
-- Event-driven orchestration triggers
-- =====================================================

CREATE TABLE IF NOT EXISTS robot_events (
    id                  BIGSERIAL PRIMARY KEY,

    robot_id            VARCHAR(50),

    event_type          VARCHAR(100) NOT NULL,

    severity            VARCHAR(20),

    source_component    VARCHAR(50),

    payload             JSONB DEFAULT '{}',

    processed           BOOLEAN DEFAULT FALSE,

    created_at          TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- MISSIONS
-- Active orchestration state
-- Mission
-- ├── Task 1
-- ├── Task 2
-- ├── Task 3
-- └── Task 4
-- =====================================================

CREATE TABLE IF NOT EXISTS missions (
    mission_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    robot_id                VARCHAR(50),

    mission_type            VARCHAR(50),

    priority                INT DEFAULT 0,

    scheduling_priority     INT DEFAULT 0,

    scheduling_status       VARCHAR(30),

    assigned_queue          VARCHAR(50),

    assigned_agent          VARCHAR(50),

    status                  VARCHAR(30),

    source_location         VARCHAR(50),

    destination_location    VARCHAR(50),

    dependency_mission_id   UUID,

    estimated_duration_s    FLOAT,

    scheduled_start_time    TIMESTAMP,

    deadline                TIMESTAMP,

    started_at              TIMESTAMP,

    completed_at            TIMESTAMP,

    metadata                JSONB DEFAULT '{}'
);

-- =====================================================
-- MISSION HISTORY
-- Historical analytics + semantic retrieval
-- =====================================================

CREATE TABLE IF NOT EXISTS mission_history (
    id                      BIGSERIAL PRIMARY KEY,

    mission_id              UUID,

    robot_id                VARCHAR(50),

    mission_type            VARCHAR(50),

    success                 BOOLEAN,

    duration_s              FLOAT,

    fail_reason             TEXT,

    mission_summary         TEXT,

    embedding               vector(1536),

    created_at              TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- MISSION QUEUE
-- Scheduling agent queue management
-- =====================================================

/*CREATE TABLE IF NOT EXISTS mission_queue (
    id                      BIGSERIAL PRIMARY KEY,

    mission_id              UUID,

    queue_name              VARCHAR(50),

    priority_score          FLOAT,

    assigned_robot_id       VARCHAR(50),

    status                  VARCHAR(30),

    inserted_at             TIMESTAMP DEFAULT NOW()
);*/

-- =====================================================
-- TASKS
-- Executable sub-step
-- Mission
-- ├── Task 1
-- ├── Task 2
-- ├── Task 3
-- └── Task 4
-- =====================================================

CREATE TABLE tasks (
    task_id                 UUID PRIMARY KEY,

    mission_id              UUID,

    robot_id                VARCHAR(50),

    task_type               VARCHAR(50),

    status                  VARCHAR(30),

    assigned_agent          VARCHAR(50),

    priority                INT DEFAULT 0,

    sequence_order          INT,

    started_at              TIMESTAMP,

    completed_at            TIMESTAMP,

    retry_count             INT DEFAULT 0,

    payload                 JSONB DEFAULT '{}',

    created_at              TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- AGENT COMMANDS
-- LLM ↔ ROS execution boundary
-- =====================================================

CREATE TABLE IF NOT EXISTS agent_commands (
    command_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    mission_id              UUID,

    robot_id                VARCHAR(50),

    source_agent            VARCHAR(50),

    command_type            VARCHAR(50),

    payload                 JSONB NOT NULL,

    priority                INT DEFAULT 0,

    status                  VARCHAR(30),

    retry_count             INT DEFAULT 0,

    validation_result       VARCHAR(30),

    created_at              TIMESTAMP DEFAULT NOW(),

    executed_at             TIMESTAMP
);

-- =====================================================
-- ACTION LIBRARY
-- Reusable validated workflows
-- =====================================================

CREATE TABLE IF NOT EXISTS action_library (
    id                      BIGSERIAL PRIMARY KEY,

    action_name             VARCHAR(100) UNIQUE NOT NULL,

    description             TEXT,

    task_type               VARCHAR(50),

    steps                   JSONB NOT NULL,

    required_tools          JSONB DEFAULT '[]',

    success_rate            FLOAT DEFAULT 0,

    average_duration_s      FLOAT,

    use_count               INT DEFAULT 0,

    embedding               vector(1536),

    created_at              TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- ANOMALY RECORDS
-- Operational intelligence + anomaly tracking
-- =====================================================

CREATE TABLE IF NOT EXISTS anomaly_records (
    anomaly_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    robot_id                VARCHAR(50),

    anomaly_type            VARCHAR(100),

    severity                VARCHAR(20),

    detected_by             VARCHAR(50),

    related_event_id        BIGINT,

    description             TEXT,

    state_snapshot          JSONB,

    resolved                BOOLEAN DEFAULT FALSE,

    created_at              TIMESTAMP DEFAULT NOW(),

    resolved_at             TIMESTAMP
);

-- =====================================================
-- RAG DOCUMENTS
-- Semantic retrieval memory
-- =====================================================

CREATE TABLE IF NOT EXISTS rag_documents (
    id                      BIGSERIAL PRIMARY KEY,

    source_type             VARCHAR(50),

    source_id               VARCHAR(100),

    title                   TEXT,

    content                 TEXT,

    metadata                JSONB DEFAULT '{}',

    embedding               vector(1536),

    created_at              TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- WORKFLOW EXECUTION
-- LangGraph orchestration state
-- =====================================================

CREATE TABLE IF NOT EXISTS workflow_execution (
    workflow_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    workflow_type           VARCHAR(50),

    status                  VARCHAR(30),

    current_node            VARCHAR(100),

    started_at              TIMESTAMP,

    updated_at              TIMESTAMP
);

-- =====================================================
-- WORKFLOW CHECKPOINTS
-- Durable workflow persistence
-- =====================================================

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id                      BIGSERIAL PRIMARY KEY,

    workflow_id             UUID,

    graph_node              VARCHAR(100),

    checkpoint_state        JSONB,

    created_at              TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- VECTOR INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_inventory_embedding
ON inventory_items
USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_mission_embedding
ON mission_history
USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_action_embedding
ON action_library
USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_rag_embedding
ON rag_documents
USING ivfflat (embedding vector_cosine_ops);

-- =====================================================
-- EVENT INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_robot_events_type
ON robot_events(event_type);

CREATE INDEX IF NOT EXISTS idx_robot_events_created
ON robot_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_robot_events_processed
ON robot_events(processed);

-- =====================================================
-- ROBOT STATE INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_robot_state_status
ON robot_state(operational_status);

CREATE INDEX IF NOT EXISTS idx_robot_state_zone
ON robot_state(current_zone);

CREATE INDEX IF NOT EXISTS idx_robot_state_updated
ON robot_state(updated_at DESC);

-- =====================================================
-- MISSION INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_missions_status
ON missions(status);

CREATE INDEX IF NOT EXISTS idx_missions_robot
ON missions(robot_id);

CREATE INDEX IF NOT EXISTS idx_missions_priority
ON missions(priority DESC);

CREATE INDEX IF NOT EXISTS idx_missions_scheduling
ON missions(scheduling_status);

CREATE INDEX IF NOT EXISTS idx_missions_deadline
ON missions(deadline);

-- =====================================================
-- COMMAND INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_agent_commands_robot
ON agent_commands(robot_id);

CREATE INDEX IF NOT EXISTS idx_agent_commands_status
ON agent_commands(status);

CREATE INDEX IF NOT EXISTS idx_agent_commands_created
ON agent_commands(created_at DESC);

-- =====================================================
-- ANOMALY INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_anomaly_robot
ON anomaly_records(robot_id);

CREATE INDEX IF NOT EXISTS idx_anomaly_type
ON anomaly_records(anomaly_type);

CREATE INDEX IF NOT EXISTS idx_anomaly_resolved
ON anomaly_records(resolved);

-- =====================================================
-- WORKFLOW INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_workflow_status
ON workflow_execution(status);

CREATE INDEX IF NOT EXISTS idx_workflow_node
ON workflow_execution(current_node);

CREATE INDEX IF NOT EXISTS idx_workflow_checkpoint_workflow
ON workflow_checkpoints(workflow_id);
