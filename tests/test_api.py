from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def _write_sample(tmp_path: Path, name: str, body: str) -> Path:
    file_path = tmp_path / name
    file_path.write_text(body, encoding="utf-8")
    return file_path


def test_upload_process_and_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

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
    client = TestClient(app)

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

