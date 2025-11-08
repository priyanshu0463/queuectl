"""Manager for multiple worker processes."""
import multiprocessing
import os
import signal
import time
from typing import List
from .worker import Worker

class WorkerManager:
    """Manages multiple worker processes."""
    
    def __init__(self, db_path: str = "data/queuectl.db"):
        """Initialize worker manager.
        
        Args:
            db_path: Path to database file
        """
        self.db_path = db_path
        self.workers: List[multiprocessing.Process] = []
        self.pid_file = "data/workers.pid"
    
    def start_workers(self, count: int = 1):
        """Start multiple worker processes.
        
        Args:
            count: Number of worker processes to start
        """
        # Stop existing workers first
        self.stop_workers()
        
        print(f"Starting {count} worker(s)...")
        
        for i in range(count):
            worker_process = multiprocessing.Process(
                target=self._worker_main,
                args=(i,),
                daemon=False
            )
            worker_process.start()
            self.workers.append(worker_process)
            print(f"Worker {i+1} started (PID: {worker_process.pid})")
        
        # Save PIDs to file
        self._save_pids()
    
    def _worker_main(self, worker_index: int):
        """Main function for worker process.
        
        Args:
            worker_index: Index of the worker
        """
        worker = Worker(worker_id=f"worker-{worker_index+1}", db_path=self.db_path)
        worker.start()
    
    def stop_workers(self, graceful: bool = True):
        """Stop all worker processes.
        
        Args:
            graceful: If True, send SIGTERM for graceful shutdown
        """
        # Load PIDs from file if workers list is empty
        if not self.workers:
            self._load_pids()
        
        if not self.workers:
            print("No workers running")
            return
        
        print(f"Stopping {len(self.workers)} worker(s)...")
        
        if graceful:
            # Send SIGTERM for graceful shutdown
            for worker in self.workers:
                if worker.is_alive():
                    try:
                        os.kill(worker.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            
            # Wait for workers to finish (with timeout)
            import time
            time.sleep(2)  # Give workers time to finish current jobs
            
            # Check if any are still alive and force kill if needed
            for worker in self.workers[:]:  # Copy list to avoid modification during iteration
                if worker.is_alive():
                    print(f"Worker {worker.pid} didn't stop gracefully, forcing...")
                    try:
                        os.kill(worker.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        else:
            # Force kill
            for worker in self.workers:
                if worker.is_alive():
                    try:
                        os.kill(worker.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        
        self.workers.clear()
        self._clear_pids()
        print("All workers stopped")
    
    def _save_pids(self):
        """Save worker PIDs to file."""
        os.makedirs(os.path.dirname(self.pid_file), exist_ok=True)
        with open(self.pid_file, 'w') as f:
            for worker in self.workers:
                f.write(f"{worker.pid}\n")
    
    def _load_pids(self):
        """Load worker PIDs from file and check if they're still running."""
        if not os.path.exists(self.pid_file):
            return
        
        try:
            with open(self.pid_file, 'r') as f:
                pids = [int(line.strip()) for line in f if line.strip()]
            
            for pid in pids:
                try:
                    # Check if process exists
                    os.kill(pid, 0)
                    # Create a minimal process-like object for tracking
                    class PidProcess:
                        def __init__(self, pid):
                            self.pid = pid
                        def is_alive(self):
                            try:
                                os.kill(self.pid, 0)
                                return True
                            except (ProcessLookupError, OSError):
                                return False
                    
                    self.workers.append(PidProcess(pid))
                except (ProcessLookupError, OSError):
                    # Process doesn't exist
                    pass
        except Exception:
            pass
    
    def _clear_pids(self):
        """Clear PID file."""
        if os.path.exists(self.pid_file):
            os.remove(self.pid_file)
    
    def get_worker_count(self) -> int:
        """Get number of active workers.
        
        Returns:
            Number of active workers
        """
        # Load PIDs if workers list is empty
        if not self.workers:
            self._load_pids()
        
        # Filter out dead processes
        self.workers = [w for w in self.workers if w.is_alive()]
        return len(self.workers)

