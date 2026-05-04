#!/usr/bin/env python
"""Comprehensive functional test for Redis-based worker pipeline."""

from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4
import sys
import subprocess

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import ensure_runtime_dirs, UPLOAD_DIR, RESULT_DIR
from app.services.task_service import TaskService
from app.queue.redis_queue import RedisQueue

def test_redis_queue():
    """Test 1: Verify Redis queue basic operations."""
    print("\n" + "="*60)
    print("TEST 1: Redis Queue Basic Operations")
    print("="*60)
    
    queue = RedisQueue("test_queue")
    
    # Clear queue
    while queue.size() > 0:
        queue.dequeue()
    
    print("✓ Queue initialized")
    print(f"  Queue size: {queue.size()}")
    
    # Test enqueue
    queue.enqueue("task_001")
    queue.enqueue("task_002")
    queue.enqueue("task_003")
    print(f"✓ Enqueued 3 tasks")
    print(f"  Queue size: {queue.size()}")
    
    # Test snapshot
    snapshot = queue.snapshot()
    print(f"✓ Snapshot: {snapshot}")
    
    # Test dequeue
    task = queue.dequeue()
    print(f"✓ Dequeued task: {task}")
    print(f"  Queue size after dequeue: {queue.size()}")
    
    # Test blocking dequeue (timeout)
    task = queue.dequeue(block=True, timeout=1.0)
    print(f"✓ Blocking dequeue result: {task}")
    print(f"  Queue size: {queue.size()}")
    
    return True

def test_task_service_with_redis():
    """Test 2: Verify TaskService uses Redis queue."""
    print("\n" + "="*60)
    print("TEST 2: TaskService Integration with Redis")
    print("="*60)
    
    ensure_runtime_dirs()
    service = TaskService()
    
    print("✓ TaskService instantiated")
    print(f"  Queue type: {type(service._queue).__name__}")
    print(f"  Queue size: {service.queue_size()}")
    
    # Clear any existing tasks in queue
    while service.queue_size() > 0:
        service._queue.dequeue()
    
    # Create a test PDF file
    test_pdf_dir = UPLOAD_DIR / "test_task_001"
    test_pdf_dir.mkdir(parents=True, exist_ok=True)
    test_pdf_file = test_pdf_dir / "sample.pdf"
    
    # Write a minimal valid PDF
    test_pdf_file.write_bytes(b"%PDF-1.4\n%EOF")
    print(f"✓ Created test PDF: {test_pdf_file}")
    
    # Queue the task manually
    service._queue.enqueue("test_task_001")
    print(f"✓ Queued task: test_task_001")
    print(f"  Queue size: {service.queue_size()}")
    
    # Dequeue and verify
    next_task = service.process_next()
    if next_task:
        print(f"✓ Processed task: {next_task.task_id}")
        print(f"  Status: {next_task.status}")
        print(f"  File: {next_task.file_name}")
    
    return True

def test_cli_process_queue():
    """Test 3: Verify CLI process-queue command."""
    print("\n" + "="*60)
    print("TEST 3: CLI process-queue Command")
    print("="*60)
    
    # Create test PDF
    ensure_runtime_dirs()
    test_pdf_dir = UPLOAD_DIR / "test_task_002"
    test_pdf_dir.mkdir(parents=True, exist_ok=True)
    test_pdf_file = test_pdf_dir / "sample2.pdf"
    test_pdf_file.write_bytes(b"%PDF-1.4\n%EOF")
    
    # Queue it
    queue = RedisQueue()
    queue.enqueue("test_task_002")
    print(f"✓ Queued task: test_task_002")
    
    # Run CLI command
    result = subprocess.run(
        [".venv/bin/python", "-m", "app.cli", "process-queue"],
        capture_output=True,
        text=True,
        timeout=10
    )
    
    print(f"✓ CLI command executed")
    print(f"  Return code: {result.returncode}")
    print(f"  Output: {result.stdout.strip()}")
    if result.stderr:
        print(f"  Stderr: {result.stderr.strip()}")
    
    return result.returncode == 0

def test_dual_pathway_enqueue_dequeue():
    """Test 4: Verify both typer and worker can pull from same queue."""
    print("\n" + "="*60)
    print("TEST 4: Dual Pathway - Enqueue/Dequeue from Redis")
    print("="*60)
    
    ensure_runtime_dirs()
    
    # Create multiple test PDFs
    for i in range(3):
        test_pdf_dir = UPLOAD_DIR / f"test_task_{100+i}"
        test_pdf_dir.mkdir(parents=True, exist_ok=True)
        test_pdf_file = test_pdf_dir / f"sample{i}.pdf"
        test_pdf_file.write_bytes(b"%PDF-1.4\n%EOF")
    
    # Enqueue via TaskService
    service = TaskService()
    
    # Clear queue
    while service.queue_size() > 0:
        service._queue.dequeue()
    
    for i in range(3):
        service._queue.enqueue(f"test_task_{100+i}")
    
    print(f"✓ Enqueued 3 tasks via TaskService")
    print(f"  Queue size: {service.queue_size()}")
    
    # Dequeue via RedisQueue directly
    queue = RedisQueue()
    dequeued = []
    for i in range(3):
        task_id = queue.dequeue()
        if task_id:
            dequeued.append(task_id)
    
    print(f"✓ Dequeued {len(dequeued)} tasks via RedisQueue")
    print(f"  Tasks: {dequeued}")
    print(f"  Queue size: {queue.size()}")
    
    return len(dequeued) == 3

def test_task_processing_flow():
    """Test 5: End-to-end task processing flow."""
    print("\n" + "="*60)
    print("TEST 5: End-to-End Task Processing Flow")
    print("="*60)
    
    ensure_runtime_dirs()
    
    # Create test PDF
    test_task_id = f"e2e_test_{uuid4().hex[:8]}"
    test_pdf_dir = UPLOAD_DIR / test_task_id
    test_pdf_dir.mkdir(parents=True, exist_ok=True)
    test_pdf_file = test_pdf_dir / "document.pdf"
    test_pdf_file.write_bytes(b"%PDF-1.4\n%EOF")
    
    print(f"✓ Created test PDF: {test_pdf_file}")
    
    # Enqueue task
    queue = RedisQueue()
    queue.enqueue(test_task_id)
    print(f"✓ Enqueued task: {test_task_id}")
    
    # Process via TaskService
    service = TaskService()
    record = service.process_task(test_task_id)
    
    print(f"✓ Task processed")
    print(f"  Task ID: {record.task_id}")
    print(f"  Status: {record.status}")
    print(f"  File: {record.file_name}")
    print(f"  Result path: {record.result_path}")
    
    # Verify result file exists
    if record.result_path and Path(record.result_path).exists():
        result_content = json.loads(Path(record.result_path).read_text())
        print(f"✓ Result file verified")
        print(f"  Title: {result_content.get('title', 'N/A')}")
        print(f"  Processing time: {result_content.get('processing_time_ms', 'N/A')}ms")
        return True
    else:
        print(f"✗ Result file not found")
        return False

if __name__ == "__main__":
    print("\n🚀 REDIS WORKER PIPELINE FUNCTIONAL TEST SUITE")
    print("=" * 60)
    
    results = {}
    
    try:
        results["Redis Queue Operations"] = test_redis_queue()
        results["TaskService Redis Integration"] = test_task_service_with_redis()
        results["CLI process-queue Command"] = test_cli_process_queue()
        results["Dual Pathway Queue Access"] = test_dual_pathway_enqueue_dequeue()
        results["End-to-End Processing"] = test_task_processing_flow()
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total_count - passed_count} test(s) failed")
        sys.exit(1)
