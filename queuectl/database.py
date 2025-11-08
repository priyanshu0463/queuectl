"""Database layer for persistent job storage using SQLite."""
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import threading

class Database:
    """Thread-safe SQLite database for job storage."""
    
    def __init__(self, db_path: str = "data/queuectl.db"):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Initialize schema
        self._init_schema()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    @contextmanager
    def _transaction(self):
        """Context manager for database transactions."""
        conn = self._get_connection()
        try:
            with self._lock:
                yield conn
                conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def _init_schema(self):
        """Initialize database schema."""
        conn = self._get_connection()
        with self._lock:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_retry_at TEXT,
                    locked_by TEXT,
                    locked_at TEXT,
                    output TEXT,
                    error TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            
            # Create indexes for better query performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_state 
                ON jobs(state)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_next_retry 
                ON jobs(next_retry_at)
            """)
            
            conn.commit()
    
    def create_job(self, job_id: str, command: str, max_retries: int = 3) -> Dict[str, Any]:
        """Create a new job.
        
        Args:
            job_id: Unique job identifier
            command: Command to execute
            max_retries: Maximum number of retry attempts
            
        Returns:
            Job dictionary
        """
        now = datetime.utcnow().isoformat() + "Z"
        with self._transaction() as conn:
            conn.execute("""
                INSERT INTO jobs (id, command, state, attempts, max_retries, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (job_id, command, "pending", 0, max_retries, now, now))
        
        return self.get_job(job_id)
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job dictionary or None if not found
        """
        conn = self._get_connection()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,)
            ).fetchone()
        
        return dict(row) if row else None
    
    def list_jobs(self, state: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """List jobs, optionally filtered by state.
        
        Args:
            state: Optional state filter
            limit: Maximum number of jobs to return
            
        Returns:
            List of job dictionaries
        """
        conn = self._get_connection()
        with self._lock:
            if state:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE state = ? ORDER BY created_at DESC LIMIT ?",
                    (state, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        
        return [dict(row) for row in rows]
    
    def acquire_job(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Acquire a pending job for processing (with locking).
        
        Args:
            worker_id: Unique worker identifier
            
        Returns:
            Job dictionary or None if no job available
        """
        conn = self._get_connection()
        with self._lock:
            # Try to get a pending job that's not locked and ready for retry
            now = datetime.utcnow().isoformat() + "Z"
            
            # First, try pending jobs
            row = conn.execute("""
                SELECT * FROM jobs 
                WHERE state = 'pending' 
                AND (locked_by IS NULL OR locked_at IS NULL OR datetime(locked_at) < datetime('now', '-5 minutes'))
                ORDER BY created_at ASC
                LIMIT 1
            """).fetchone()
            
            # If no pending job, try failed jobs that are ready for retry
            if not row:
                row = conn.execute("""
                    SELECT * FROM jobs 
                    WHERE state = 'failed' 
                    AND attempts < max_retries
                    AND (next_retry_at IS NULL OR datetime(next_retry_at) <= datetime('now'))
                    AND (locked_by IS NULL OR locked_at IS NULL OR datetime(locked_at) < datetime('now', '-5 minutes'))
                    ORDER BY created_at ASC
                    LIMIT 1
                """).fetchone()
            
            if row:
                job = dict(row)
                # Lock the job
                conn.execute("""
                    UPDATE jobs 
                    SET state = 'processing', 
                        locked_by = ?,
                        locked_at = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (worker_id, now, now, job['id']))
                conn.commit()
                job['state'] = 'processing'
                job['locked_by'] = worker_id
                job['locked_at'] = now
                return job
            
            return None
    
    def update_job(self, job_id: str, **kwargs) -> Dict[str, Any]:
        """Update job fields.
        
        Args:
            job_id: Job identifier
            **kwargs: Fields to update
            
        Returns:
            Updated job dictionary
        """
        now = datetime.utcnow().isoformat() + "Z"
        updates = []
        values = []
        
        for key, value in kwargs.items():
            if key in ['state', 'attempts', 'next_retry_at', 'output', 'error', 'locked_by', 'locked_at']:
                updates.append(f"{key} = ?")
                values.append(value)
        
        if updates:
            updates.append("updated_at = ?")
            values.append(now)
            values.append(job_id)
            
            with self._transaction() as conn:
                conn.execute(
                    f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                    values
                )
        
        return self.get_job(job_id)
    
    def release_job_lock(self, job_id: str):
        """Release lock on a job.
        
        Args:
            job_id: Job identifier
        """
        with self._transaction() as conn:
            conn.execute("""
                UPDATE jobs 
                SET locked_by = NULL, locked_at = NULL
                WHERE id = ?
            """, (job_id,))
    
    def get_stats(self) -> Dict[str, int]:
        """Get statistics about job states.
        
        Returns:
            Dictionary with state counts
        """
        conn = self._get_connection()
        with self._lock:
            rows = conn.execute("""
                SELECT state, COUNT(*) as count
                FROM jobs
                GROUP BY state
            """).fetchall()
        
        stats = {row['state']: row['count'] for row in rows}
        return {
            'pending': stats.get('pending', 0),
            'processing': stats.get('processing', 0),
            'completed': stats.get('completed', 0),
            'failed': stats.get('failed', 0),
            'dead': stats.get('dead', 0),
        }
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value.
        
        Args:
            key: Configuration key
            default: Default value if not found
            
        Returns:
            Configuration value
        """
        conn = self._get_connection()
        with self._lock:
            row = conn.execute(
                "SELECT value FROM config WHERE key = ?",
                (key,)
            ).fetchone()
        
        if row:
            value = row['value']
            # Try to parse as JSON for complex types
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        
        return default
    
    def set_config(self, key: str, value: Any):
        """Set configuration value.
        
        Args:
            key: Configuration key
            value: Configuration value (will be JSON-encoded if needed)
        """
        # Convert value to string/JSON
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value)
        else:
            value_str = str(value)
        
        with self._transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO config (key, value)
                VALUES (?, ?)
            """, (key, value_str))
    
    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration values.
        
        Returns:
            Dictionary of all configuration key-value pairs
        """
        conn = self._get_connection()
        with self._lock:
            rows = conn.execute("SELECT key, value FROM config").fetchall()
        
        config = {}
        for row in rows:
            try:
                config[row['key']] = json.loads(row['value'])
            except (json.JSONDecodeError, TypeError):
                config[row['key']] = row['value']
        
        return config

