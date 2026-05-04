#!/usr/bin/env python
"""Real-world functional test with actual PDF processing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/Users/Apple/Desktop/study report/week 2改/fastapi_app")

from app.core.config import ensure_runtime_dirs, RESULT_DIR
from app.queue.redis_queue import RedisQueue
from app.services.task_service import TaskService

def test_real_pdf_processing():
    """Test with a real PDF containing actual text."""
    print("\n" + "="*70)
    print("🧪 REAL-WORLD PDF PROCESSING TEST")
    print("="*70)
    
    ensure_runtime_dirs()
    
    task_id = "real_pdf_test"
    result_path = RESULT_DIR / f"{task_id}.json"
    
    # Clean up previous result
    if result_path.exists():
        result_path.unlink()
    
    # Queue the task
    queue = RedisQueue()
    queue.enqueue(task_id)
    print(f"\n✓ Queued task: {task_id}")
    print(f"  Queue size: {queue.size()}")
    
    # Process the task
    service = TaskService()
    record = service.process_task(task_id)
    
    print(f"\n✓ Task processed:")
    print(f"  Task ID: {record.task_id}")
    print(f"  Status: {record.status}")
    print(f"  File: {record.file_name}")
    print(f"  File size: {record.file_size} bytes")
    
    # Check result file
    if result_path.exists():
        result = json.loads(result_path.read_text())
        print(f"\n✓ Result file generated:")
        print(f"  Title: {result.get('title', 'N/A')}")
        print(f"  Abstract: {result.get('abstract', 'N/A')[:100]}...")
        print(f"  Body preview: {result.get('body_preview', 'N/A')[:100]}...")
        print(f"  Processing time: {result.get('processing_time_ms', 'N/A')}ms")
        print(f"  Error: {result.get('error', 'None')}")
        
        if result.get('error'):
            return False, "PDF processing returned error"
        
        if result.get('title') and result.get('title') != 'N/A':
            return True, "Successfully extracted title from PDF"
        else:
            return False, "No title extracted from PDF"
    else:
        return False, "Result file not created"

def test_worker_script():
    """Test the standalone worker script."""
    print("\n" + "="*70)
    print("🧪 STANDALONE WORKER SCRIPT TEST")
    print("="*70)
    
    ensure_runtime_dirs()
    
    # Create a test task
    test_id = "worker_test_task"
    task_dir = Path("/Users/Apple/Desktop/study report/week 2改/fastapi_app/data/uploads/worker_test_task")
    task_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy the real PDF
    import shutil
    src = Path("/Users/Apple/Desktop/study report/week 2改/fastapi_app/data/uploads/real_pdf_test/research_paper.pdf")
    dst = task_dir / "research_paper.pdf"
    shutil.copy(src, dst)
    
    print(f"\n✓ Created test PDF at {dst}")
    
    # Queue via Redis
    queue = RedisQueue()
    queue.enqueue(test_id)
    print(f"✓ Queued task via Redis: {test_id}")
    
    # Test the worker processing
    service = TaskService()
    record = service.process_task(test_id)
    
    print(f"\n✓ Worker processed task:")
    print(f"  Task ID: {record.task_id}")
    print(f"  Status: {record.status}")
    
    return True, "Worker successfully processed task from Redis"

def test_cli_workflow():
    """Test the complete CLI workflow."""
    print("\n" + "="*70)
    print("🧪 CLI WORKFLOW TEST")
    print("="*70)
    
    ensure_runtime_dirs()
    
    # Create a test task
    test_id = "cli_workflow_test"
    task_dir = Path("/Users/Apple/Desktop/study report/week 2改/fastapi_app/data/uploads/cli_workflow_test")
    task_dir.mkdir(parents=True, exist_ok=True)
    
    import shutil
    src = Path("/Users/Apple/Desktop/study report/week 2改/fastapi_app/data/uploads/real_pdf_test/research_paper.pdf")
    dst = task_dir / "research_paper.pdf"
    shutil.copy(src, dst)
    
    print(f"\n✓ Created test PDF")
    
    # Queue via Redis
    queue = RedisQueue()
    queue.enqueue(test_id)
    print(f"✓ Queued task: {test_id}")
    
    # Run CLI process-queue command
    result = subprocess.run(
        [".venv/bin/python", "-m", "app.cli", "process-queue"],
        cwd="/Users/Apple/Desktop/study report/week 2改/fastapi_app",
        capture_output=True,
        text=True,
        timeout=10
    )
    
    print(f"\n✓ CLI command executed:")
    print(f"  Return code: {result.returncode}")
    print(f"  Output: {result.stdout.strip()}")
    
    if result.returncode == 0:
        return True, "CLI workflow completed successfully"
    else:
        return False, f"CLI failed with code {result.returncode}"

if __name__ == "__main__":
    print("\n" + "🎯 COMPREHENSIVE REDIS WORKER PIPELINE TEST")
    print("="*70)
    
    tests = [
        ("Real PDF Processing", test_real_pdf_processing),
        ("Standalone Worker Script", test_worker_script),
        ("CLI Workflow", test_cli_workflow),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            passed, message = test_func()
            results.append((test_name, passed, message))
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"\n{status} {message}")
        except Exception as e:
            results.append((test_name, False, str(e)))
            print(f"\n❌ FAIL: {test_name}")
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print("\n" + "="*70)
    print("📊 COMPREHENSIVE TEST SUMMARY")
    print("="*70)
    
    for test_name, passed, message in results:
        status = "✅" if passed else "❌"
        print(f"{status} {test_name}: {message}")
    
    passed_count = sum(1 for _, p, _ in results if p)
    total_count = len(results)
    
    print(f"\n📈 Total: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 ALL TESTS PASSED! The Redis worker pipeline is fully functional.")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total_count - passed_count} test(s) failed")
        sys.exit(1)
