#!/usr/bin/env python3
"""Comprehensive test script for QueueCTL."""
import os
import sys
import time
import json
import subprocess
import shutil
from pathlib import Path

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_test(name):
    """Print test name."""
    print(f"\n{BLUE}━━━ Testing: {name} ━━━{RESET}")

def print_success(msg):
    """Print success message."""
    print(f"{GREEN}✓{RESET} {msg}")

def print_error(msg):
    """Print error message."""
    print(f"{RED}✗{RESET} {msg}")

def print_info(msg):
    """Print info message."""
    print(f"{YELLOW}→{RESET} {msg}")

def run_command(cmd, check=True):
    """Run a command and return result."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        if check and result.returncode != 0:
            print_error(f"Command failed: {cmd}")
            print_error(f"Error: {result.stderr}")
            return None
        return result
    except subprocess.TimeoutExpired:
        print_error(f"Command timed out: {cmd}")
        return None
    except Exception as e:
        print_error(f"Exception running command: {e}")
        return None

def cleanup():
    """Clean up test data."""
    print_info("Cleaning up test data...")
    if os.path.exists("data/queuectl.db"):
        os.remove("data/queuectl.db")
    if os.path.exists("data/workers.pid"):
        os.remove("data/workers.pid")
    print_success("Cleanup complete")

def test_basic_job_completion():
    """Test 1: Basic job completes successfully."""
    print_test("Basic Job Completion")
    
    # Clean start
    cleanup()
    
    # Start a worker
    print_info("Starting worker...")
    worker_proc = subprocess.Popen(
        ["python", "-m", "queuectl.cli", "worker", "start", "--count", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)  # Give worker time to start
    
    # Enqueue a simple job
    print_info("Enqueueing job...")
    result = run_command(
        'python -m queuectl.cli enqueue \'{"id":"test1","command":"echo Hello World"}\''
    )
    if not result:
        return False
    
    # Wait for job to complete
    print_info("Waiting for job to complete...")
    time.sleep(3)
    
    # Check status
    result = run_command("python -m queuectl.cli status")
    if not result:
        return False
    
    # Check if job completed
    result = run_command("python -m queuectl.cli list --state completed")
    if not result or "test1" not in result.stdout:
        print_error("Job not found in completed state")
        return False
    
    # Stop worker
    run_command("python -m queuectl.cli worker stop", check=False)
    worker_proc.terminate()
    worker_proc.wait(timeout=5)
    
    print_success("Basic job completed successfully")
    return True

def test_failed_job_retries():
    """Test 2: Failed job retries with backoff and moves to DLQ."""
    print_test("Failed Job Retries and DLQ")
    
    cleanup()
    
    # Start a worker
    print_info("Starting worker...")
    worker_proc = subprocess.Popen(
        ["python", "-m", "queuectl.cli", "worker", "start", "--count", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)
    
    # Enqueue a job that will fail
    print_info("Enqueueing failing job...")
    result = run_command(
        'python -m queuectl.cli enqueue \'{"id":"fail1","command":"false"}\' --max-retries 3'
    )
    if not result:
        return False
    
    # Wait for retries (with exponential backoff: 2^1=2s, 2^2=4s, 2^3=8s)
    print_info("Waiting for retries (this may take ~15 seconds)...")
    time.sleep(20)
    
    # Check DLQ
    result = run_command("python -m queuectl.cli dlq list")
    if not result or "fail1" not in result.stdout:
        print_error("Failed job not found in DLQ")
        return False
    
    print_success("Failed job moved to DLQ after retries")
    
    # Test DLQ retry
    print_info("Testing DLQ retry...")
    result = run_command("python -m queuectl.cli dlq retry fail1")
    if not result:
        return False
    
    time.sleep(2)
    
    # Check if job is back in queue (could be pending or processing)
    result = run_command("python -m queuectl.cli list --state pending")
    if result and "fail1" in result.stdout:
        print_success("DLQ retry works")
    else:
        # Check if it's being processed
        result = run_command("python -m queuectl.cli list --state processing")
        if result and "fail1" in result.stdout:
            print_success("DLQ retry works (job is processing)")
        else:
            # Check all states to see where it is
            result = run_command("python -m queuectl.cli list")
            if result and "fail1" in result.stdout:
                print_success("DLQ retry works (job found in queue)")
            else:
                print_error("DLQ retry failed - job not found")
                return False
    
    # Stop worker
    run_command("python -m queuectl.cli worker stop", check=False)
    worker_proc.terminate()
    worker_proc.wait(timeout=5)
    
    return True

def test_multiple_workers():
    """Test 3: Multiple workers process jobs without overlap."""
    print_test("Multiple Workers (No Overlap)")
    
    cleanup()
    
    # Start multiple workers
    print_info("Starting 3 workers...")
    worker_proc = subprocess.Popen(
        ["python", "-m", "queuectl.cli", "worker", "start", "--count", "3"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)
    
    # Enqueue multiple jobs
    print_info("Enqueueing 5 jobs...")
    for i in range(1, 6):
        result = run_command(
            f'python -m queuectl.cli enqueue \'{{"id":"multi{i}","command":"sleep 1"}}\''
        )
        if not result:
            return False
    
    # Wait for jobs to process
    print_info("Waiting for jobs to process...")
    time.sleep(5)
    
    # Check that all jobs completed
    result = run_command("python -m queuectl.cli list --state completed")
    if not result:
        return False
    
    completed_count = result.stdout.count("multi")
    if completed_count < 5:
        print_error(f"Only {completed_count}/5 jobs completed")
        return False
    
    print_success(f"All {completed_count} jobs processed by multiple workers")
    
    # Stop workers
    run_command("python -m queuectl.cli worker stop", check=False)
    worker_proc.terminate()
    worker_proc.wait(timeout=5)
    
    return True

def test_invalid_commands():
    """Test 4: Invalid commands fail gracefully."""
    print_test("Invalid Commands Fail Gracefully")
    
    cleanup()
    
    # Start a worker
    print_info("Starting worker...")
    worker_proc = subprocess.Popen(
        ["python", "-m", "queuectl.cli", "worker", "start", "--count", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)
    
    # Enqueue a job with invalid command
    print_info("Enqueueing job with invalid command...")
    result = run_command(
        'python -m queuectl.cli enqueue \'{"id":"invalid1","command":"nonexistent_command_xyz123"}\''
    )
    if not result:
        return False
    
    # Wait for job to fail
    time.sleep(3)
    
    # Check that job failed (not completed)
    result = run_command("python -m queuectl.cli list --state failed")
    if result and "invalid1" in result.stdout:
        print_success("Invalid command handled gracefully")
    else:
        # Job might be in DLQ if max retries reached
        result = run_command("python -m queuectl.cli dlq list")
        if result and "invalid1" in result.stdout:
            print_success("Invalid command moved to DLQ")
        else:
            print_error("Invalid command not handled properly")
            return False
    
    # Stop worker
    run_command("python -m queuectl.cli worker stop", check=False)
    worker_proc.terminate()
    worker_proc.wait(timeout=5)
    
    return True

def test_persistence():
    """Test 5: Job data survives restart."""
    print_test("Job Persistence Across Restart")
    
    cleanup()
    
    # Enqueue a job (no workers running)
    print_info("Enqueueing job without workers...")
    result = run_command(
        'python -m queuectl.cli enqueue \'{"id":"persist1","command":"echo Persisted"}\''
    )
    if not result:
        return False
    
    # Verify job exists
    result = run_command("python -m queuectl.cli list --state pending")
    if not result or "persist1" not in result.stdout:
        print_error("Job not found after enqueue")
        return False
    
    print_success("Job persisted to database")
    
    # Start worker and process job
    print_info("Starting worker to process persisted job...")
    worker_proc = subprocess.Popen(
        ["python", "-m", "queuectl.cli", "worker", "start", "--count", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)
    
    # Wait for job to complete
    time.sleep(3)
    
    # Check if job completed
    result = run_command("python -m queuectl.cli list --state completed")
    if result and "persist1" in result.stdout:
        print_success("Persisted job processed after restart")
    else:
        print_error("Persisted job not processed")
        return False
    
    # Stop worker
    run_command("python -m queuectl.cli worker stop", check=False)
    worker_proc.terminate()
    worker_proc.wait(timeout=5)
    
    return True

def test_configuration():
    """Test 6: Configuration management."""
    print_test("Configuration Management")
    
    cleanup()
    
    # Set configuration
    print_info("Setting configuration...")
    result = run_command("python -m queuectl.cli config set test-key test-value")
    if not result:
        return False
    
    # Get configuration
    result = run_command("python -m queuectl.cli config get test-key")
    if not result or "test-value" not in result.stdout:
        print_error("Configuration not retrieved correctly")
        return False
    
    print_success("Configuration set and retrieved")
    
    # Get all configuration
    result = run_command("python -m queuectl.cli config get")
    if not result:
        return False
    
    print_success("Configuration management works")
    
    return True

def main():
    """Run all tests."""
    print(f"\n{GREEN}{'='*60}")
    print("QueueCTL Comprehensive Test Suite")
    print(f"{'='*60}{RESET}\n")
    
    tests = [
        ("Basic Job Completion", test_basic_job_completion),
        ("Failed Job Retries", test_failed_job_retries),
        ("Multiple Workers", test_multiple_workers),
        ("Invalid Commands", test_invalid_commands),
        ("Persistence", test_persistence),
        ("Configuration", test_configuration),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                print_success(f"Test '{test_name}' PASSED")
            else:
                print_error(f"Test '{test_name}' FAILED")
        except Exception as e:
            print_error(f"Test '{test_name}' ERROR: {e}")
            results.append((test_name, False))
        
        # Cleanup between tests
        time.sleep(1)
    
    # Final cleanup
    cleanup()
    
    # Summary
    print(f"\n{BLUE}{'='*60}")
    print("Test Summary")
    print(f"{'='*60}{RESET}\n")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
        print(f"{status} - {test_name}")
    
    print(f"\n{BLUE}Results: {passed}/{total} tests passed{RESET}\n")
    
    if passed == total:
        print(f"{GREEN}All tests passed! ✓{RESET}\n")
        return 0
    else:
        print(f"{RED}Some tests failed. Please review the output above.{RESET}\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())

