from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def _configure_runtime_dirs(tmp_path: Path, monkeypatch) -> None:
    upload_dir = tmp_path / "data" / "uploads"
    result_dir = tmp_path / "data" / "results"
    monkeypatch.setattr("app.services.task_service.UPLOAD_DIR", upload_dir)
    monkeypatch.setattr("app.services.task_service.RESULT_DIR", result_dir)
    monkeypatch.setattr("app.core.config.UPLOAD_DIR", upload_dir)
    monkeypatch.setattr("app.core.config.RESULT_DIR", result_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)


def _write_sample(tmp_path: Path, name: str, body: str) -> Path:
    file_path = tmp_path / name
    file_path.write_text(body, encoding="utf-8")
    return file_path


def _write_sample_pdf(tmp_path: Path, name: str = "sample.pdf") -> Path:
    file_path = tmp_path / name
    file_path.write_bytes(
        b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 128 >>
stream
BT
(Sample PDF Title.) Tj
(Abstract: This PDF is used to test extraction.) Tj
(Body content appears here for preview assertions.) Tj
ET
endstream
endobj
%%EOF
"""
    )
    return file_path


def test_upload_process_and_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _configure_runtime_dirs(tmp_path, monkeypatch)

    with TestClient(app) as client:
        sample = _write_sample(tmp_path, "sample.txt", "INFO hello\nWARN caution\nERROR fail\n")
        with sample.open("rb") as handle:
            response = client.post("/upload", files={"file": ("sample.txt", handle, "text/plain")})

        assert response.status_code == 200
        payload = response.json()
        task_id = payload["tasks"][0]["task_id"]

        detail = client.get(f"/tasks/{task_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "queued"

        processed = client.post("/tasks/process-next")
        assert processed.status_code == 200
        assert processed.json()["processed"][0]["status"] == "success"

        result = client.get(f"/tasks/{task_id}/result")
        assert result.status_code == 200
        result_payload = result.json()
        assert result_payload["result"]["total_lines"] == 3
        assert result_payload["result"]["error_count"] == 1
        assert result_payload["result"]["warn_count"] == 1


def test_batch_upload_and_task_filter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _configure_runtime_dirs(tmp_path, monkeypatch)

    with TestClient(app) as client:
        file_one = _write_sample(tmp_path, "first.log", "WARN one\nINFO two\n")
        file_two = _write_sample(tmp_path, "second.csv", "a,b\n1,2\nERROR row\n")

        with file_one.open("rb") as first, file_two.open("rb") as second:
            response = client.post(
                "/upload/batch",
                files=[
                    ("files", ("first.log", first, "text/plain")),
                    ("files", ("second.csv", second, "text/csv")),
                ],
            )

        assert response.status_code == 200
        assert len(response.json()["tasks"]) == 2

        queued = client.get("/tasks?status=queued")
        assert queued.status_code == 200
        assert len(queued.json()) == 2


def test_pdf_upload_process_and_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _configure_runtime_dirs(tmp_path, monkeypatch)

    with TestClient(app) as client:
        sample = _write_sample_pdf(tmp_path)
        with sample.open("rb") as handle:
            response = client.post("/upload", files={"file": ("sample.pdf", handle, "application/pdf")})

        assert response.status_code == 200
        payload = response.json()
        task_id = payload["task_id"]
        assert task_id == payload["tasks"][0]["task_id"]

        storage_path = Path(client.get(f"/tasks/{task_id}").json()["storage_path"])
        assert storage_path.parent.name == task_id
        assert storage_path.name == "sample.pdf"

        processed = client.post("/tasks/process-next")
        assert processed.status_code == 200
        assert processed.json()["processed"][0]["status"] == "success"

        result = client.get(f"/tasks/{task_id}/result")
        assert result.status_code == 200
        result_payload = result.json()["result"]
        assert result_payload["title"] == "Sample PDF Title."
        assert "test extraction" in result_payload["abstract"]
        assert "Body content" in result_payload["body_preview"]
