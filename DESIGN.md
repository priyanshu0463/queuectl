# QueueCTL - Architecture & Design Document

## Overview

QueueCTL is a CLI-based background job queue system built with Python. It provides a production-grade solution for managing background jobs with automatic retries, exponential backoff, and Dead Letter Queue (DLQ) support.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Interface                         │
│                    (queuectl/cli.py)                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ enqueue  │  │  status  │  │   list   │  │  config  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Database Layer                            │
│                  (queuectl/database.py)                      │
│              SQLite with Thread-Safe Operations              │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Job Model   │    │   Workers    │    │   Config     │
│ (job.py)     │    │ (worker.py)  │    │  Management  │
└──────────────┘    └──────────────┘    └──────────────┘
        │                    │
        │                    │
        ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│              Worker Manager (worker_manager.py)             │
│         Manages Multiple Worker Processes                    │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Database Layer (`database.py`)

**Purpose**: Provides persistent, thread-safe storage for jobs and configuration.

**Key Features**:
- **SQLite Database**: Lightweight, file-based database requiring no external services
- **Thread-Safe Operations**: Uses threading locks and thread-local connections
- **Transaction Support**: Ensures data consistency with rollback on errors
- **Indexed Queries**: Optimized queries with indexes on state and retry times

**Schema**:
```sql
jobs:
  - id (PRIMARY KEY)
  - command (TEXT)
  - state (TEXT: pending|processing|completed|failed|dead)
  - attempts (INTEGER)
  - max_retries (INTEGER)
  - created_at (TEXT: ISO 8601)
  - updated_at (TEXT: ISO 8601)
  - next_retry_at (TEXT: ISO 8601, nullable)
  - locked_by (TEXT: worker_id, nullable)
  - locked_at (TEXT: ISO 8601, nullable)
  - output (TEXT, nullable)
  - error (TEXT, nullable)

config:
  - key (PRIMARY KEY)
  - value (TEXT: JSON-encoded)
```

**Design Decisions**:
- **SQLite over PostgreSQL/MySQL**: No external dependencies, perfect for CLI tool
- **Thread-local connections**: Each thread gets its own connection for safety
- **Lock-based transactions**: Ensures atomic operations across threads
- **ISO 8601 timestamps**: Standardized, sortable date format

### 2. Job Model (`job.py`)

**Purpose**: Represents a single job with execution logic.

**Key Features**:
- **Command Execution**: Uses `subprocess.run()` to execute shell commands
- **State Management**: Handles state transitions (pending → processing → completed/failed)
- **Retry Logic**: Calculates exponential backoff delays
- **Error Handling**: Captures stdout, stderr, and exit codes

**Job Lifecycle**:
```
pending → processing → completed
                ↓
              failed → (wait for backoff) → retry → ... → dead (DLQ)
```

**Design Decisions**:
- **Shell execution**: Supports any shell command, flexible but requires security considerations
- **Timeout protection**: 5-minute default timeout prevents hung jobs
- **Exit code based**: Standard Unix convention (0 = success, non-zero = failure)

### 3. Worker Process (`worker.py`)

**Purpose**: Single worker that processes jobs from the queue.

**Key Features**:
- **Job Acquisition**: Atomically locks and acquires pending/failed jobs
- **Signal Handling**: Graceful shutdown on SIGTERM/SIGINT
- **Retry Scheduling**: Implements exponential backoff
- **Error Recovery**: Releases locks on crashes (5-minute expiry)

**Worker Loop**:
```python
while running:
    1. Acquire job (with lock)
    2. Execute job command
    3. Update job state (completed/failed/dead)
    4. Release lock
    5. Poll for next job
```

**Design Decisions**:
- **Process-based**: Uses multiprocessing for true parallelism (not threads)
- **Lock expiry**: 5-minute timeout handles crashed workers
- **Polling interval**: Configurable (default 1 second) for responsiveness vs CPU usage

### 4. Worker Manager (`worker_manager.py`)

**Purpose**: Manages multiple worker processes.

**Key Features**:
- **Process Management**: Starts/stops multiple worker processes
- **PID Tracking**: Maintains PID file for process tracking
- **Graceful Shutdown**: Sends SIGTERM, waits, then SIGKILL if needed
- **Process Discovery**: Can find and manage workers started in other sessions

**Design Decisions**:
- **PID file**: Simple persistence mechanism for worker tracking
- **Multiprocessing**: Each worker is a separate process (better isolation)
- **Graceful shutdown**: 2-second wait allows current jobs to finish

### 5. CLI Interface (`cli.py`)

**Purpose**: User-facing command-line interface.

**Key Features**:
- **Typer Framework**: Modern CLI framework with automatic help generation
- **Rich Output**: Beautiful tables and colored output using Rich library
- **Command Grouping**: Logical grouping (worker, dlq, config subcommands)
- **Error Handling**: User-friendly error messages

**Command Structure**:
```
queuectl
├── enqueue          # Add job to queue
├── status           # Show queue statistics
├── list             # List jobs (with filters)
├── worker
│   ├── start        # Start workers
│   └── stop         # Stop workers
├── dlq
│   ├── list         # List DLQ jobs
│   └── retry         # Retry DLQ job
└── config
    ├── set          # Set config
    ├── get          # Get config
    └── unset        # Remove config
```

## Data Flow

### Job Enqueueing
```
User → CLI → Database.create_job() → SQLite INSERT → Job in 'pending' state
```

### Job Processing
```
Worker Loop:
  1. Database.acquire_job() → SELECT + UPDATE (with lock)
  2. Job.execute() → subprocess.run()
  3. Job.mark_completed() or Job.mark_failed()
  4. Database.update_job() → UPDATE state
```

### Retry Flow
```
Failed Job:
  1. Calculate delay = base ^ attempts
  2. Set next_retry_at = now + delay
  3. State = 'failed'
  4. Worker polls for jobs where next_retry_at <= now
  5. After max_retries → State = 'dead' (DLQ)
```

## Concurrency Model

### Job Locking
- **Purpose**: Prevent multiple workers from processing the same job
- **Mechanism**: `locked_by` and `locked_at` fields in database
- **Acquisition**: Atomic SELECT + UPDATE in transaction
- **Expiry**: 5-minute timeout (handles crashed workers)
- **Release**: Explicit unlock on completion/failure

### Thread Safety
- **Database**: Thread-local connections + global lock for transactions
- **Workers**: Separate processes (no shared memory issues)
- **PID File**: File-based locking handled by OS

## Retry Strategy

### Exponential Backoff
```
delay = base ^ attempts (seconds)

Example with base=2:
  Attempt 1: 2^1 = 2 seconds
  Attempt 2: 2^2 = 4 seconds
  Attempt 3: 2^3 = 8 seconds
```

### Retry States
1. **Failed**: Job failed, waiting for retry (next_retry_at set)
2. **Dead**: Max retries exhausted, moved to DLQ
3. **Retry from DLQ**: Reset attempts, move back to pending

## Configuration System

### Storage
- **Location**: SQLite `config` table
- **Format**: JSON-encoded values (supports complex types)
- **Scope**: Global (affects all workers)

### Key Configuration
- `max-retries`: Default max retries (overridable per job)
- `backoff-base`: Base for exponential backoff calculation
- `poll-interval`: Seconds between worker polls

## Error Handling

### Job Execution Errors
- **Command not found**: Captured, job marked failed
- **Non-zero exit code**: Treated as failure, triggers retry
- **Timeout**: 5-minute default, job marked failed
- **Exception**: Caught, error stored, job marked failed

### System Errors
- **Database locked**: Retry with timeout (30 seconds)
- **Worker crash**: Lock expires after 5 minutes, job becomes available
- **Invalid JSON**: User-friendly error message, no job created

## Performance Considerations

### Database
- **Indexes**: On `state` and `next_retry_at` for fast queries
- **Connection Pooling**: Thread-local connections (one per thread)
- **Transaction Size**: Small transactions for better concurrency

### Workers
- **Polling**: Configurable interval (default 1 second)
- **Process Overhead**: Multiprocessing has overhead, but provides true parallelism
- **Lock Contention**: Minimal due to atomic operations

## Scalability

### Current Limitations
- **Single Database**: SQLite has write concurrency limits
- **File-based**: Not suitable for distributed systems
- **No Priority Queues**: All jobs treated equally

### Future Enhancements
- **PostgreSQL Backend**: For distributed deployments
- **Redis Queue**: For high-throughput scenarios
- **Job Priorities**: Priority-based scheduling
- **Scheduled Jobs**: Cron-like scheduling
- **Job Dependencies**: DAG-based job execution

## Security Considerations

### Command Execution
- **Shell Injection**: Commands executed via shell (potential risk)
- **Recommendation**: Validate/sanitize commands in production
- **User Permissions**: Workers run with same permissions as CLI user

### Database
- **File Permissions**: SQLite file should be protected
- **SQL Injection**: Parameterized queries prevent injection

## Testing Strategy

### Test Coverage
- **Unit Tests**: Individual component testing (not included, but recommended)
- **Integration Tests**: End-to-end workflow testing (`test_queuectl.py`)
- **Manual Testing**: CLI commands verified manually

### Test Scenarios
1. Basic job completion
2. Failed job retries with backoff
3. Multiple workers (no overlap)
4. Invalid commands (graceful failure)
5. Persistence across restarts
6. Configuration management

## Deployment Considerations

### Installation
- **Virtual Environment**: Recommended for isolation
- **Dependencies**: Minimal (typer, rich)
- **Python Version**: 3.8+ required

### Data Directory
- **Location**: `data/` directory (created automatically)
- **Contents**: `queuectl.db` (SQLite), `workers.pid` (PID tracking)
- **Backup**: Regular backups recommended for production

### Monitoring
- **Status Command**: Quick health check
- **Logs**: Worker output to stdout/stderr
- **Metrics**: Job counts, worker counts (via status command)

## Trade-offs & Design Decisions

### SQLite vs PostgreSQL
- **Chosen**: SQLite
- **Reason**: No external dependencies, perfect for CLI tool
- **Trade-off**: Limited write concurrency, not distributed

### Process vs Thread Workers
- **Chosen**: Multiprocessing
- **Reason**: True parallelism, better isolation
- **Trade-off**: Higher memory overhead, slower startup

### Polling vs Event-Driven
- **Chosen**: Polling
- **Reason**: Simpler implementation, no external dependencies
- **Trade-off**: Slight delay in job pickup (1 second default)

### File-based vs Database Config
- **Chosen**: Database
- **Reason**: Consistent with job storage, easier to query
- **Trade-off**: Slightly more complex than config file

## Future Enhancements

### Potential Features
1. **Job Priorities**: Priority-based scheduling
2. **Scheduled Jobs**: Cron-like `run_at` field
3. **Job Timeouts**: Per-job timeout configuration
4. **Job Output Logging**: Persistent log files
5. **Metrics Dashboard**: Web UI for monitoring
6. **Job Dependencies**: DAG-based execution
7. **Rate Limiting**: Throttle job execution
8. **Job Groups**: Batch operations on job groups

### Architecture Improvements
1. **Message Queue Backend**: Redis/RabbitMQ for distributed systems
2. **REST API**: HTTP interface alongside CLI
3. **Plugin System**: Custom job types
4. **Distributed Workers**: Workers across multiple machines
5. **Job Replay**: Re-execute completed jobs

## Conclusion

QueueCTL provides a robust, production-ready job queue system with a clean architecture, clear separation of concerns, and comprehensive error handling. The design prioritizes simplicity, reliability, and ease of use while maintaining the flexibility to extend for future requirements.

