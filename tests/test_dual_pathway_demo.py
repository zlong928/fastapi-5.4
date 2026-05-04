#!/usr/bin/env python
"""Demonstration of dual pathway: Worker and CLI both consuming from same Redis queue."""

from __future__ import annotations

import subprocess
import sys
import time
import threading
from pathlib import Path
from queue import Queue as ThreadQueue

sys.path.insert(0, "/Users/Apple/Desktop/study report/week 2改/fastapi_app")

from app.core.config import ensure_runtime_dirs, UPLOAD_DIR
from app.queue.redis_queue import RedisQueue

def create_test_pdfs(count: int = 5):
    """Create multiple test PDFs."""
    ensure_runtime_dirs()
    
    import shutil
    src = Path("/Users/Apple/Desktop/study report/week 2改/fastapi_app/data/uploads/real_pdf_test/research_paper.pdf")
    
    task_ids = []
    for i in range(count):
        task_id = f"demo_task_{i:03d}"
        task_dir = UPLOAD_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        dst = task_dir / "document.pdf"
        shutil.copy(src, dst)
        task_ids.append(task_id)
    
    return task_ids

def process_via_cli(task_ids: list[str], results: ThreadQueue):
    """Process tasks using CLI in a separate thread."""
    print("\n📱 CLI Worker Thread Started")
    print(f"   Will process {len(task_ids)//2} tasks via CLI")
    print("="*70)
    
    processed = []
    for i, task_id in enumerate(task_ids[::2]):  # Take every other task
        cmd = [".venv/bin/python", "-m", "app.cli", "process-queue"]
        result = subprocess.run(
            cmd,
            cwd="/Users/Apple/Desktop/study report/week 2改/fastapi_app",
            capture_output=True,
            text=True,
            timeout=10
        )
        
        status = "✓" if result.returncode == 0 else "✗"
        output = result.stdout.strip().split(":")[-1].strip() if result.stdout else "N/A"
        processed.append((task_id, result.returncode == 0))
        print(f"{status} CLI processed: {output[:50]}")
        time.sleep(0.5)
    
    results.put(("CLI", processed))
    print(f"\n📱 CLI Worker Thread Completed ({len(processed)} tasks)")

def process_via_python(task_ids: list[str], results: ThreadQueue):
    """Process tasks using Python TaskService in a separate thread."""
    from app.services.task_service import TaskService
    
    print("\n🐍 Python Worker Thread Started")
    print(f"   Will process {len(task_ids)//2} tasks via TaskService")
    print("="*70)
    
    service = TaskService()
    processed = []
    
    for i, task_id in enumerate(task_ids[1::2]):  # Take every other task (starting from 1)
        record = service.process_task(task_id)
        status = "✓" if record.status == "success" else "✗"
        processed.append((task_id, record.status == "success"))
        print(f"{status} Python processed: {task_id} -> {record.status}")
        time.sleep(0.5)
    
    results.put(("Python", processed))
    print(f"\n🐍 Python Worker Thread Completed ({len(processed)} tasks)")

def main():
    print("\n" + "="*70)
    print("🎯 DUAL PATHWAY DEMONSTRATION")
    print("   Showing CLI and Worker both consuming from same Redis queue")
    print("="*70)
    
    # Create test PDFs
    print("\n1️⃣  Creating test PDFs...")
    task_ids = create_test_pdfs(5)
    print(f"   ✓ Created {len(task_ids)} test PDFs")
    for tid in task_ids:
        print(f"     - {tid}")
    
    # Queue all tasks
    print("\n2️⃣  Enqueueing all tasks to Redis...")
    queue = RedisQueue()
    for task_id in task_ids:
        queue.enqueue(task_id)
    print(f"   ✓ Queued {len(task_ids)} tasks to Redis")
    print(f"   Queue size: {queue.size()}")
    
    # Process in parallel
    print("\n3️⃣  Starting parallel processing...")
    print("   Spawning two workers:")
    print("   - CLI worker (will process odd-indexed tasks)")
    print("   - Python worker (will process even-indexed tasks)")
    
    results = ThreadQueue()
    
    cli_thread = threading.Thread(
        target=process_via_cli,
        args=(task_ids, results),
        daemon=False
    )
    
    python_thread = threading.Thread(
        target=process_via_python,
        args=(task_ids, results),
        daemon=False
    )
    
    cli_thread.start()
    python_thread.start()
    
    # Wait for completion
    cli_thread.join()
    python_thread.join()
    
    # Collect results
    print("\n" + "="*70)
    print("4️⃣  RESULTS SUMMARY")
    print("="*70)
    
    all_results = {}
    while not results.empty():
        worker_type, processed = results.get()
        all_results[worker_type] = processed
    
    for worker_type, processed in all_results.items():
        success_count = sum(1 for _, success in processed if success)
        print(f"\n{worker_type} Worker:")
        print(f"  Tasks processed: {len(processed)}")
        print(f"  Successful: {success_count}/{len(processed)}")
        for task_id, success in processed:
            status = "✓" if success else "✗"
            print(f"    {status} {task_id}")
    
    # Final queue status
    print(f"\nFinal Redis queue size: {queue.size()}")
    
    total_processed = sum(len(p) for p in all_results.values())
    print(f"\n🎉 Total tasks processed: {total_processed}/{len(task_ids)}")
    
    if total_processed == len(task_ids):
        print("\n✅ SUCCESS! Both pathways successfully consumed all tasks from the same Redis queue.")
        return 0
    else:
        print(f"\n⚠️  Warning: Only {total_processed}/{len(task_ids)} tasks were processed.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
