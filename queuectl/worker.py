"""Worker process for executing jobs."""
import time
import signal
import sys
import uuid
from typing import Optional
from .database import Database
from .job import Job

class Worker:
    """Worker process that executes jobs from the queue."""
    
    def __init__(self, worker_id: Optional[str] = None, db_path: str = "data/queuectl.db"):
        """Initialize worker.
        
        Args:
            worker_id: Unique worker identifier (auto-generated if not provided)
            db_path: Path to database file
        """
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.db = Database(db_path)
        self.running = False
        self.current_job: Optional[Job] = None
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\n[{self.worker_id}] Received shutdown signal, finishing current job...")
        self.running = False
    
    def start(self):
        """Start the worker loop."""
        self.running = True
        print(f"[{self.worker_id}] Worker started")
        
        while self.running:
            try:
                # Get configuration
                backoff_base = self.db.get_config('backoff-base', 2)
                poll_interval = self.db.get_config('poll-interval', 1)
                
                # Try to acquire a job
                job_data = self.db.acquire_job(self.worker_id)
                
                if job_data:
                    self.current_job = Job(self.db, job_data)
                    self._process_job(backoff_base)
                    self.current_job = None
                else:
                    # No job available, wait before polling again
                    time.sleep(poll_interval)
                    
            except KeyboardInterrupt:
                self.running = False
                break
            except Exception as e:
                print(f"[{self.worker_id}] Error in worker loop: {e}")
                time.sleep(1)
        
        # Release any locked job on shutdown
        if self.current_job:
            print(f"[{self.worker_id}] Releasing lock on current job...")
            self.db.release_job_lock(self.current_job.id)
        
        print(f"[{self.worker_id}] Worker stopped")
    
    def _process_job(self, backoff_base: int):
        """Process a single job.
        
        Args:
            backoff_base: Base for exponential backoff
        """
        job = self.current_job
        print(f"[{self.worker_id}] Processing job {job.id}: {job.command}")
        
        # Execute the job
        success, output, error = job.execute()
        
        if success:
            job.mark_completed(output)
            print(f"[{self.worker_id}] Job {job.id} completed successfully")
        else:
            job.mark_failed(error, backoff_base)
            if job.state == 'dead':
                print(f"[{self.worker_id}] Job {job.id} moved to DLQ after {job.attempts} attempts")
            else:
                print(f"[{self.worker_id}] Job {job.id} failed (attempt {job.attempts}/{job.max_retries}), will retry")

