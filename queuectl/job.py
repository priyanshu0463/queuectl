"""Job model and execution logic."""
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from .database import Database

class Job:
    """Represents a background job."""
    
    def __init__(self, db: Database, job_data: Dict[str, Any]):
        """Initialize job from database record.
        
        Args:
            db: Database instance
            job_data: Job data from database
        """
        self.db = db
        self.id = job_data['id']
        self.command = job_data['command']
        self.state = job_data['state']
        self.attempts = job_data['attempts']
        self.max_retries = job_data['max_retries']
        self.created_at = job_data['created_at']
        self.updated_at = job_data['updated_at']
        self.next_retry_at = job_data.get('next_retry_at')
        self.locked_by = job_data.get('locked_by')
        self.locked_at = job_data.get('locked_at')
        self.output = job_data.get('output')
        self.error = job_data.get('error')
    
    def execute(self, timeout: int = 300) -> Tuple[bool, Optional[str], Optional[str]]:
        """Execute the job command.
        
        Args:
            timeout: Maximum execution time in seconds
            
        Returns:
            Tuple of (success, output, error)
        """
        try:
            # Execute the command
            result = subprocess.run(
                self.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            output = result.stdout
            error = result.stderr if result.returncode != 0 else None
            
            # Command succeeded if return code is 0
            success = result.returncode == 0
            
            return success, output, error
            
        except subprocess.TimeoutExpired:
            return False, None, f"Command timed out after {timeout} seconds"
        except FileNotFoundError:
            return False, None, f"Command not found: {self.command}"
        except Exception as e:
            return False, None, str(e)
    
    def mark_completed(self, output: Optional[str] = None):
        """Mark job as completed.
        
        Args:
            output: Optional output from command execution
        """
        self.db.update_job(
            self.id,
            state='completed',
            output=output,
            locked_by=None,
            locked_at=None
        )
        self.state = 'completed'
    
    def mark_failed(self, error: Optional[str] = None, backoff_base: int = 2):
        """Mark job as failed and schedule retry if applicable.
        
        Args:
            error: Error message
            backoff_base: Base for exponential backoff calculation
        """
        new_attempts = self.attempts + 1
        
        if new_attempts >= self.max_retries:
            # Move to DLQ
            self.db.update_job(
                self.id,
                state='dead',
                attempts=new_attempts,
                error=error,
                locked_by=None,
                locked_at=None
            )
            self.state = 'dead'
        else:
            # Calculate next retry time with exponential backoff
            delay_seconds = backoff_base ** new_attempts
            next_retry = (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat() + "Z"
            
            self.db.update_job(
                self.id,
                state='failed',
                attempts=new_attempts,
                next_retry_at=next_retry,
                error=error,
                locked_by=None,
                locked_at=None
            )
            self.state = 'failed'
            self.next_retry_at = next_retry
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary.
        
        Returns:
            Job as dictionary
        """
        return {
            'id': self.id,
            'command': self.command,
            'state': self.state,
            'attempts': self.attempts,
            'max_retries': self.max_retries,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'next_retry_at': self.next_retry_at,
            'locked_by': self.locked_by,
            'locked_at': self.locked_at,
            'output': self.output,
            'error': self.error,
        }

