# QueueCTL - Background Job Queue System

A production-grade CLI-based background job queue system with worker processes, automatic retries with exponential backoff, and Dead Letter Queue (DLQ) support.

## 🚀 Features

- ✅ **Job Enqueueing**: Add background jobs via CLI
- ✅ **Multiple Workers**: Run multiple worker processes in parallel
- ✅ **Automatic Retries**: Failed jobs retry with exponential backoff
- ✅ **Dead Letter Queue**: Permanently failed jobs moved to DLQ
- ✅ **Persistent Storage**: SQLite database for job persistence
- ✅ **Job Locking**: Prevents duplicate job processing
- ✅ **Graceful Shutdown**: Workers finish current jobs before stopping
- ✅ **Configuration Management**: Configurable retry count and backoff base
- ✅ **Rich CLI Interface**: Beautiful terminal output with tables and colors

## 📋 Requirements

- Python 3.8 or higher
- pip

## 🔧 Installation

### Option 1: Install from source

```bash
# Clone the repository
git clone <repository-url>
cd queuectl

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

### Option 2: Direct execution

```bash
# Install dependencies
pip install -r requirements.txt

# Run directly
python -m queuectl.cli
```

## 📖 Usage

### Basic Commands

#### Enqueue a Job

```bash
queuectl enqueue '{"id":"job1","command":"echo Hello World"}'
```

With custom max retries:
```bash
queuectl enqueue '{"id":"job2","command":"sleep 2"}' --max-retries 5
```

#### Start Workers

```bash
# Start a single worker
queuectl worker start

# Start multiple workers
queuectl worker start --count 3
```

#### Stop Workers

```bash
queuectl worker stop
```

#### Check Status

```bash
queuectl status
```

Output shows:
- Pending jobs count
- Processing jobs count
- Completed jobs count
- Failed jobs count
- Dead Letter Queue count
- Active workers count

#### List Jobs

```bash
# List all jobs
queuectl list

# List jobs by state
queuectl list --state pending
queuectl list --state completed
queuectl list --state failed
queuectl list --state dead

# Limit results
queuectl list --state pending --limit 10
```

#### Dead Letter Queue

```bash
# List all jobs in DLQ
queuectl dlq list

# Retry a job from DLQ
queuectl dlq retry job1
```

#### Configuration

```bash
# Set configuration
queuectl config set max-retries 5
queuectl config set backoff-base 3
queuectl config set poll-interval 2

# Get configuration
queuectl config get max-retries

# Get all configuration
queuectl config get

# Remove configuration
queuectl config unset max-retries
```

## 🏗️ Architecture Overview

### Job Lifecycle

```
pending → processing → completed
                ↓
              failed → (retry with backoff) → failed → ... → dead (DLQ)
```

### Components

1. **Database Layer** (`database.py`): SQLite-based persistent storage with thread-safe operations
2. **Job Model** (`job.py`): Job representation with execution logic
3. **Worker** (`worker.py`): Single worker process that executes jobs
4. **Worker Manager** (`worker_manager.py`): Manages multiple worker processes
5. **CLI Interface** (`cli.py`): Command-line interface using Typer

### Job States

- **pending**: Waiting to be picked up by a worker
- **processing**: Currently being executed by a worker
- **completed**: Successfully executed
- **failed**: Failed, but retryable (will retry with exponential backoff)
- **dead**: Permanently failed (moved to DLQ after max retries)

### Retry Mechanism

Failed jobs automatically retry with exponential backoff:
- Delay = `base ^ attempts` seconds
- Default base: 2
- Example: 1st retry after 2s, 2nd after 4s, 3rd after 8s

### Job Locking

- Jobs are locked when acquired by a worker
- Lock prevents duplicate processing
- Locks expire after 5 minutes (handles crashed workers)
- Lock is released when job completes or fails

## 🧪 Testing

A comprehensive test script is provided to validate all core flows:

```bash
python test_queuectl.py
```

The test script validates:
1. ✅ Basic job completion
2. ✅ Failed job retries with backoff
3. ✅ Multiple workers processing jobs without overlap
4. ✅ Invalid commands fail gracefully
5. ✅ Job data persistence across restarts
6. ✅ Dead Letter Queue functionality
7. ✅ Configuration management

## 📁 Project Structure

```
queuectl/
├── queuectl/
│   ├── __init__.py
│   ├── cli.py              # CLI interface
│   ├── database.py         # Database layer
│   ├── job.py              # Job model
│   ├── worker.py           # Worker process
│   └── worker_manager.py   # Worker manager
├── data/                   # Data directory (created automatically)
│   ├── queuectl.db         # SQLite database
│   └── workers.pid         # Worker PID file
├── requirements.txt        # Python dependencies
├── setup.py               # Package setup
├── test_queuectl.py       # Test script
└── README.md              # This file
```

## 🔍 Example Workflows

### Example 1: Simple Job Execution

```bash
# 1. Start a worker
queuectl worker start --count 1

# 2. Enqueue a job
queuectl enqueue '{"id":"test1","command":"echo Hello from QueueCTL"}'

# 3. Check status
queuectl status

# 4. List completed jobs
queuectl list --state completed
```

### Example 2: Testing Retries

```bash
# 1. Start workers
queuectl worker start --count 2

# 2. Enqueue a job that will fail
queuectl enqueue '{"id":"fail1","command":"false"}' --max-retries 3

# 3. Monitor the job
queuectl list --state failed
queuectl list --state dead

# 4. Check DLQ
queuectl dlq list
```

### Example 3: Multiple Workers

```bash
# 1. Start 3 workers
queuectl worker start --count 3

# 2. Enqueue multiple jobs
for i in {1..10}; do
  queuectl enqueue "{\"id\":\"job$i\",\"command\":\"sleep 1\"}"
done

# 3. Monitor processing
queuectl status
queuectl list --state processing
```

## ⚙️ Configuration

Default configuration values:
- `max-retries`: 3 (can be overridden per job)
- `backoff-base`: 2 (exponential backoff base)
- `poll-interval`: 1 (seconds between worker polls)

## 🛠️ Assumptions & Trade-offs

### Assumptions

1. **Command Execution**: Jobs execute shell commands using `subprocess.run()`
2. **Success Criteria**: Exit code 0 = success, non-zero = failure
3. **Timeout**: Default 300 seconds (5 minutes) per job
4. **Lock Expiry**: 5 minutes (handles crashed workers)
5. **Database**: SQLite for simplicity and portability

### Trade-offs

1. **SQLite vs PostgreSQL/MySQL**: Chose SQLite for simplicity, no external dependencies
2. **File-based vs Database**: Using SQLite provides better concurrency and querying
3. **Process-based Workers**: Using multiprocessing for true parallelism (vs threads)
4. **No Job Priorities**: Simplified implementation (can be added as bonus feature)
5. **No Scheduled Jobs**: Focused on immediate execution (can be added as bonus feature)

## 🐛 Troubleshooting

### Workers not processing jobs

- Check if workers are running: `queuectl status`
- Verify jobs are in pending state: `queuectl list --state pending`
- Check for locked jobs: `queuectl list --state processing`

### Jobs stuck in processing

- Locks expire after 5 minutes automatically
- Or manually stop and restart workers: `queuectl worker stop`

### Database locked errors

- Ensure only one process is accessing the database
- Check for crashed workers and clean up PID file

## 📝 License

This project is part of a backend developer internship assignment.

## 🤝 Contributing

This is an assignment project. For questions or issues, please refer to the assignment requirements.

## ✅ Checklist

- [x] All required commands functional
- [x] Jobs persist after restart
- [x] Retry and backoff implemented correctly
- [x] DLQ operational
- [x] CLI user-friendly and documented
- [x] Code is modular and maintainable
- [x] Includes test script verifying main flows
- [x] Comprehensive README

## 🎥 Demo

A working CLI demo video is available at: [Link to be added]

---

**Built with ❤️ using Python, Typer, and SQLite**

