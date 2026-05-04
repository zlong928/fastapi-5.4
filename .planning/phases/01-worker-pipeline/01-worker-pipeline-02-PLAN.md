---
phase: 01-worker-pipeline
plan: 02
type: execute
wave: 2
depends_on: ["01"]
files_modified: ["app/cli.py", "app/worker.py"]
autonomous: true
requirements: ["TYPER-01", "WORKER-01"]
must_haves:
  truths:
    - "Typer CLI can fetch tasks from Redis and process them"
    - "Standalone worker script can run continuously to process tasks"
  artifacts:
    - path: "app/worker.py"
      provides: "Standalone background worker pipeline"
  key_links:
    - from: "app/worker.py"
      to: "app/services/task_service.py"
      via: "dequeue and process"
---

<objective>
Update Typer CLI and create standalone worker for automated pipeline.
Purpose: Enable multiple pathways (CLI and worker) to fetch and process tasks from Redis.
Output: Updated `cli.py` and new `worker.py` script.
</objective>

<context>
@app/cli.py
@app/services/task_service.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update Typer CLI for Redis</name>
  <files>app/cli.py</files>
  <action>
    Add a new Typer command `process-queue` that fetches ONE task from the queue and processes it.
    Use `TaskService().process_next()`.
    Ensure `cli.py` doesn't conflict with background worker. The background worker in `TaskService` (start_background_worker) should be disabled when running via CLI to avoid race conditions.
  </action>
  <verify>
    <automated>python -m app.cli --help | grep process-queue</automated>
  </verify>
  <done>CLI has process-queue command</done>
</task>

<task type="auto">
  <name>Task 2: Create Standalone Worker</name>
  <files>app/worker.py</files>
  <action>
    Create `app/worker.py` that continuously runs and fetches tasks from Redis.
    It should instantiate `TaskService` (ensuring internal background worker is disabled if needed) and loop over `service.process_next()` in a blocking manner.
    Add logging to show when it starts, when it picks up a task, and when it finishes.
    Implement graceful shutdown on KeyboardInterrupt (SIGINT/SIGTERM).
  </action>
  <verify>
    <automated>python -c "import app.worker"</automated>
  </verify>
  <done>Worker module exists and is runnable</done>
</task>

</tasks>
