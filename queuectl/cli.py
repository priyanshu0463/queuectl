"""CLI interface for QueueCTL."""
import typer
import json
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich import box
from .database import Database
from .worker_manager import WorkerManager
from .job import Job

app = typer.Typer(help="QueueCTL - Simple Job Queue CLI")
console = Console()

# Sub-apps for grouping commands
worker_app = typer.Typer(help="Worker management commands")
dlq_app = typer.Typer(help="Dead Letter Queue commands")
config_app = typer.Typer(help="Configuration management")

app.add_typer(worker_app, name="worker")
app.add_typer(dlq_app, name="dlq")
app.add_typer(config_app, name="config")

# Default database path
DB_PATH = "data/queuectl.db"


@app.command()
def enqueue(
    job_data: str = typer.Argument(..., help="Job data as JSON string"),
    max_retries: int = typer.Option(3, "--max-retries", "-r", help="Maximum retry attempts")
):
    """Enqueue a new job to the queue.
    
    Example:
        queuectl enqueue '{"id":"job1","command":"echo hello"}'
    """
    try:
        # Parse job data
        if isinstance(job_data, str):
            job_dict = json.loads(job_data)
        else:
            job_dict = job_data
        
        job_id = job_dict.get('id')
        command = job_dict.get('command')
        
        if not job_id:
            console.print("[red]Error: Job must have an 'id' field[/red]")
            raise typer.Exit(1)
        
        if not command:
            console.print("[red]Error: Job must have a 'command' field[/red]")
            raise typer.Exit(1)
        
        # Get max_retries from job data or parameter
        job_max_retries = job_dict.get('max_retries', max_retries)
        
        # Create job in database
        db = Database(DB_PATH)
        job = db.create_job(job_id, command, job_max_retries)
        
        console.print(f"[green]✓[/green] Job [bold]{job_id}[/bold] enqueued successfully")
        console.print(f"  Command: {command}")
        console.print(f"  Max retries: {job_max_retries}")
        
    except json.JSONDecodeError:
        console.print("[red]Error: Invalid JSON format[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@worker_app.command("start")
def worker_start(
    count: int = typer.Option(1, "--count", "-c", help="Number of workers to start")
):
    """Start one or more worker processes.
    
    Example:
        queuectl worker start --count 3
    """
    try:
        manager = WorkerManager(DB_PATH)
        manager.start_workers(count)
        console.print(f"[green]✓[/green] Started {count} worker(s)")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@worker_app.command("stop")
def worker_stop():
    """Stop all running worker processes gracefully.
    
    Example:
        queuectl worker stop
    """
    try:
        manager = WorkerManager(DB_PATH)
        manager.stop_workers(graceful=True)
        console.print("[green]✓[/green] All workers stopped")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def status():
    """Show summary of all job states and active workers.
    
    Example:
        queuectl status
    """
    try:
        db = Database(DB_PATH)
        stats = db.get_stats()
        
        # Get worker count
        manager = WorkerManager(DB_PATH)
        worker_count = manager.get_worker_count()
        
        # Create status table
        table = Table(title="Queue Status", box=box.ROUNDED)
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Value", style="magenta")
        
        table.add_row("Pending Jobs", str(stats['pending']))
        table.add_row("Processing Jobs", str(stats['processing']))
        table.add_row("Completed Jobs", str(stats['completed']))
        table.add_row("Failed Jobs", str(stats['failed']))
        table.add_row("Dead Letter Queue", str(stats['dead']))
        table.add_row("Active Workers", str(worker_count))
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def list(
    state: Optional[str] = typer.Option(None, "--state", "-s", help="Filter by job state"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of jobs to show")
):
    """List jobs, optionally filtered by state.
    
    Example:
        queuectl list --state pending
        queuectl list --state completed --limit 10
    """
    try:
        db = Database(DB_PATH)
        jobs = db.list_jobs(state=state, limit=limit)
        
        if not jobs:
            console.print("[yellow]No jobs found[/yellow]")
            return
        
        # Create jobs table
        table = Table(title=f"Jobs" + (f" ({state})" if state else ""), box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("Command", style="green")
        table.add_column("State", style="yellow")
        table.add_column("Attempts", style="blue")
        table.add_column("Created At", style="magenta")
        
        for job in jobs:
            state_style = {
                'pending': 'yellow',
                'processing': 'blue',
                'completed': 'green',
                'failed': 'red',
                'dead': 'red bold'
            }.get(job['state'], 'white')
            
            table.add_row(
                job['id'],
                job['command'][:50] + "..." if len(job['command']) > 50 else job['command'],
                f"[{state_style}]{job['state']}[/{state_style}]",
                f"{job['attempts']}/{job['max_retries']}",
                job['created_at'][:19] if job['created_at'] else "N/A"
            )
        
        console.print(table)
        console.print(f"\n[dim]Showing {len(jobs)} job(s)[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@dlq_app.command("list")
def dlq_list(
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of jobs to show")
):
    """List all jobs in the Dead Letter Queue.
    
    Example:
        queuectl dlq list
    """
    try:
        db = Database(DB_PATH)
        jobs = db.list_jobs(state='dead', limit=limit)
        
        if not jobs:
            console.print("[yellow]Dead Letter Queue is empty[/yellow]")
            return
        
        # Create DLQ table
        table = Table(title="Dead Letter Queue", box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("Command", style="green")
        table.add_column("Attempts", style="red")
        table.add_column("Error", style="red")
        table.add_column("Created At", style="magenta")
        
        for job in jobs:
            error = job.get('error', 'N/A')
            if error and len(error) > 50:
                error = error[:50] + "..."
            
            table.add_row(
                job['id'],
                job['command'][:50] + "..." if len(job['command']) > 50 else job['command'],
                f"{job['attempts']}/{job['max_retries']}",
                error or "N/A",
                job['created_at'][:19] if job['created_at'] else "N/A"
            )
        
        console.print(table)
        console.print(f"\n[dim]Showing {len(jobs)} job(s) in DLQ[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@dlq_app.command("retry")
def dlq_retry(
    job_id: str = typer.Argument(..., help="Job ID to retry from DLQ")
):
    """Retry a job from the Dead Letter Queue.
    
    Example:
        queuectl dlq retry job1
    """
    try:
        db = Database(DB_PATH)
        job_data = db.get_job(job_id)
        
        if not job_data:
            console.print(f"[red]Error: Job {job_id} not found[/red]")
            raise typer.Exit(1)
        
        if job_data['state'] != 'dead':
            console.print(f"[yellow]Warning: Job {job_id} is not in DLQ (state: {job_data['state']})[/yellow]")
        
        # Reset job to pending state
        db.update_job(
            job_id,
            state='pending',
            attempts=0,
            next_retry_at=None,
            error=None,
            locked_by=None,
            locked_at=None
        )
        
        console.print(f"[green]✓[/green] Job [bold]{job_id}[/bold] moved back to queue for retry")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key"),
    value: str = typer.Argument(..., help="Configuration value")
):
    """Set a configuration value.
    
    Example:
        queuectl config set max-retries 5
        queuectl config set backoff-base 3
    """
    try:
        db = Database(DB_PATH)
        
        # Try to convert value to appropriate type
        if value.isdigit():
            value = int(value)
        elif value.replace('.', '').isdigit():
            value = float(value)
        elif value.lower() in ('true', 'false'):
            value = value.lower() == 'true'
        
        db.set_config(key, value)
        console.print(f"[green]✓[/green] Configuration [bold]{key}[/bold] set to [bold]{value}[/bold]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@config_app.command("get")
def config_get(
    key: Optional[str] = typer.Argument(None, help="Configuration key (omit to show all)")
):
    """Get a configuration value or all configuration.
    
    Example:
        queuectl config get max-retries
        queuectl config get
    """
    try:
        db = Database(DB_PATH)
        
        if key:
            value = db.get_config(key)
            if value is None:
                console.print(f"[yellow]Configuration key '{key}' not found[/yellow]")
            else:
                console.print(f"[bold]{key}[/bold]: {value}")
        else:
            # Show all configuration
            config = db.get_all_config()
            
            if not config:
                console.print("[yellow]No configuration set[/yellow]")
                return
            
            table = Table(title="Configuration", box=box.ROUNDED)
            table.add_column("Key", style="cyan")
            table.add_column("Value", style="magenta")
            
            for k, v in config.items():
                table.add_row(k, str(v))
            
            console.print(table)
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(..., help="Configuration key to remove")
):
    """Remove a configuration value.
    
    Example:
        queuectl config unset max-retries
    """
    try:
        db = Database(DB_PATH)
        # Delete from config table using a transaction
        with db._transaction() as conn:
            conn.execute("DELETE FROM config WHERE key = ?", (key,))
        
        console.print(f"[green]✓[/green] Configuration [bold]{key}[/bold] removed")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
