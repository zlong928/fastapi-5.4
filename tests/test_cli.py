import json
from pathlib import Path

from typer.testing import CliRunner

from app.cli import app


def _configure_runtime_dirs(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    upload_dir = tmp_path / "data" / "uploads"
    result_dir = tmp_path / "data" / "results"
    monkeypatch.setattr("app.services.task_service.UPLOAD_DIR", upload_dir)
    monkeypatch.setattr("app.services.task_service.RESULT_DIR", result_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir, result_dir


def _write_pdf(upload_dir: Path, task_id: str, file_name: str = "sample.pdf") -> Path:
    task_dir = upload_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = task_dir / file_name
    pdf_path.write_bytes(
        b"%PDF-1.4\nBT\n(CLI PDF Title.) Tj\n(Abstract: CLI abstract.) Tj\n(CLI body preview.) Tj\nET\n%%EOF\n"
    )
    return pdf_path


def test_process_single_task_writes_result(tmp_path, monkeypatch):
    upload_dir, result_dir = _configure_runtime_dirs(tmp_path, monkeypatch)
    _write_pdf(upload_dir, "task-one")

    result = CliRunner().invoke(app, ["process", "task-one"])

    assert result.exit_code == 0
    assert "task-one: success" in result.output
    payload = json.loads((result_dir / "task-one.json").read_text(encoding="utf-8"))
    assert payload["title"] == "CLI PDF Title."
    assert payload["abstract"] == "CLI abstract. CLI body preview."


def test_scan_processes_pending_and_skips_existing_results(tmp_path, monkeypatch):
    upload_dir, result_dir = _configure_runtime_dirs(tmp_path, monkeypatch)
    _write_pdf(upload_dir, "pending-task")
    _write_pdf(upload_dir, "done-task")
    existing_result = result_dir / "done-task.json"
    existing_result.write_text(
        json.dumps(
            {
                "file_name": "sample.pdf",
                "file_size": 10,
                "file_type": "pdf",
                "processing_time_ms": 1.0,
                "title": "Existing",
                "abstract": "Existing",
                "body_preview": "Existing",
            }
        ),
        encoding="utf-8",
    )
    before = existing_result.stat().st_mtime_ns

    result = CliRunner().invoke(app, ["scan"])

    assert result.exit_code == 0
    assert "pending-task: success" in result.output
    assert "done-task" not in result.output
    assert (result_dir / "pending-task.json").exists()
    assert existing_result.stat().st_mtime_ns == before


def test_scan_records_parse_failures_without_stopping_batch(tmp_path, monkeypatch):
    upload_dir, result_dir = _configure_runtime_dirs(tmp_path, monkeypatch)
    _write_pdf(upload_dir, "valid-task")
    bad_dir = upload_dir / "bad-task"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "bad.pdf").write_bytes(b"not a pdf")

    result = CliRunner().invoke(app, ["scan"])

    assert result.exit_code == 0
    assert "bad-task: failed" in result.output
    assert "valid-task: success" in result.output
    failure = json.loads((result_dir / "bad-task.json").read_text(encoding="utf-8"))
    assert failure["error"] == "Invalid PDF header."
