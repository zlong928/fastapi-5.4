import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import Document, DocumentAsset, DocumentEvent, ExtractionJob, ExtractionResult, PaperTable, User
from app.services.agent.paper_data_adapter import PaperDataAdapter
from app.services.paper_demo_service import PaperDemoService
from app.services.agent.coordinator import FallbackExtractionCoordinator
from app.services.agent.types import FigureInfo, PaperData


class _FakeStreamResponse:
    def __init__(self, lines: list[str], content_type: str = "text/event-stream", status_code: int = 200) -> None:
        self.lines = lines
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self):
        return iter(self.lines)

    def read(self):
        return "\n".join(self.lines).encode("utf-8")


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db(db_session_factory):
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def user(db):
    user = User(email="paper@example.com", username="paperuser", hashed_password=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def client(db_session_factory, user):
    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_fallback_coordinator_aggregates_with_not_found_metrics_argument():
    paper = PaperData(
        paper_id="paper-1",
        title="Microbial wastewater treatment",
        content="materials include hydrogel chambers. key_metrics include hexanoic acid yield.",
        figures=[
            FigureInfo(
                figure_id="Figure 1 [asset:9]",
                image_path="",
                caption="Conceptual figure for microbial consortia.",
                context="Conceptual figure for microbial consortia.",
            )
        ],
    )

    events = list(FallbackExtractionCoordinator().extract(paper=paper, user_query="提取关键指标"))
    finish = events[-1]

    assert finish["phase"] == "FINISH"
    assert finish["results"]["paper_id"] == "paper-1"
    assert "by_metric" in finish["results"]


def test_openai_coordinator_uses_streaming_chat_as_primary_path(monkeypatch):
    from app.services.agent.coordinator import OpenAIExtractionCoordinator

    requests = []

    def fake_stream(method, url, headers, json, timeout):
        requests.append({"method": method, "url": url, "json": json, "timeout": timeout})
        return _FakeStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":"{\\"metrics\\":["}}]}',
                'data: {"choices":[{"delta":{"content":"\\"materials\\"]}"}}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr("app.services.agent.llm_client.httpx.stream", fake_stream)

    coordinator = OpenAIExtractionCoordinator({
        "base_url": "https://api.example.test/v1",
        "api_key": "test-key",
        "model": "test-model",
        "api_format": "openai_chat",
        "http_retries": 0,
        "min_request_interval_seconds": 0,
    })

    assert coordinator.client.chat_json([{"role": "user", "content": "plan"}], phase="planning") == {"metrics": ["materials"]}
    assert requests[0]["json"]["stream"] is True
    assert coordinator.client.token_stats["planning"]["total_tokens"] == 5


def test_gpt_models_use_streaming_openai_chat_payload_first(monkeypatch):
    from app.services.agent.llm_client import LLMClient

    requests = []

    def fake_stream(method, url, headers, json, timeout):
        requests.append({"url": url, "json": json})
        return _FakeStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":"{\\"metrics\\":[\\"materials\\"]}"}}]}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr("app.services.agent.llm_client.httpx.stream", fake_stream)

    client = LLMClient({
        "base_url": "https://api.example.test/v1",
        "api_key": "test-key",
        "model": "gpt-5.5",
        "api_format": "openai_chat",
        "http_retries": 0,
        "min_request_interval_seconds": 0,
    })

    assert client.chat_json([{"role": "user", "content": "plan"}], phase="planning") == {"metrics": ["materials"]}
    assert requests[0]["json"] == {
        "model": "gpt-5.5",
        "messages": [{"role": "user", "content": "plan"}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "stream": True,
    }


def test_responses_format_uses_openai_responses_endpoint(monkeypatch):
    from app.services.agent.llm_client import LLMClient

    requests = []

    class FakePostResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"output_text":"{\\"metrics\\":[\\"materials\\"]}"}'

        def json(self):
            return {
                "output_text": '{"metrics":["materials"]}',
                "usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
            }

    def fake_post(url, headers, json, timeout):
        requests.append({"url": url, "json": json})
        return FakePostResponse()

    monkeypatch.setattr("app.services.agent.llm_client.httpx.post", fake_post)

    client = LLMClient({
        "base_url": "https://api.example.test/v1",
        "api_key": "test-key",
        "model": "gpt-5.5",
        "api_format": "responses",
        "http_retries": 0,
        "min_request_interval_seconds": 0,
    })

    assert client.chat_json([{"role": "user", "content": "plan"}], phase="planning") == {"metrics": ["materials"]}
    assert requests[0]["url"] == "https://api.example.test/v1/responses"
    assert requests[0]["json"] == {
        "model": "gpt-5.5",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "plan"}]}],
        "store": False,
    }


def test_openai_coordinator_falls_back_to_non_streaming_only_when_enabled(monkeypatch):
    from app.services.agent.coordinator import OpenAIExtractionCoordinator

    requests = []

    def fail_stream(*args, **kwargs):
        raise RuntimeError("stream unavailable")

    class FakePostResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"choices":[{"message":{"content":"{\\"metrics\\":[\\"materials\\"]}"}}]}'

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": '{"metrics":["materials"]}'}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
            }

    def fake_post(url, headers, json, timeout):
        requests.append({"url": url, "json": json})
        return FakePostResponse()

    monkeypatch.setattr("app.services.agent.llm_client.httpx.stream", fail_stream)
    monkeypatch.setattr("app.services.agent.llm_client.httpx.post", fake_post)

    coordinator = OpenAIExtractionCoordinator({
        "base_url": "https://api.example.test/v1",
        "api_key": "test-key",
        "model": "test-model",
        "api_format": "openai_chat",
        "http_retries": 0,
        "min_request_interval_seconds": 0,
        "allow_non_stream_fallback": True,
    })

    assert coordinator.client.chat_json([{"role": "user", "content": "plan"}], phase="planning") == {"metrics": ["materials"]}
    assert requests[0]["json"]["stream"] is False
    assert coordinator.client.token_stats["planning"]["total_tokens"] == 9


def test_openai_coordinator_retries_without_response_format_when_gateway_rejects_it(monkeypatch):
    from app.services.agent.coordinator import OpenAIExtractionCoordinator

    requests = []

    def fake_stream(method, url, headers, json, timeout):
        requests.append({"url": url, "json": json})
        if "response_format" in json:
            raise RuntimeError("response_format unsupported")
        return _FakeStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":"{\\"metrics\\":["}}]}',
                'data: {"choices":[{"delta":{"content":"\\"yield\\"]}"}}]}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr("app.services.agent.llm_client.httpx.stream", fake_stream)

    coordinator = OpenAIExtractionCoordinator({
        "base_url": "https://api.example.test/v1",
        "api_key": "test-key",
        "model": "test-model",
        "api_format": "openai_chat",
        "http_retries": 0,
        "min_request_interval_seconds": 0,
    })

    assert coordinator.client.chat_json([{"role": "user", "content": "plan"}], phase="planning") == {"metrics": ["yield"]}
    assert "response_format" in requests[0]["json"]
    assert "response_format" not in requests[-1]["json"]


def test_openai_coordinator_reports_gateway_error_instead_of_html_json_parse(monkeypatch):
    from app.services.agent.coordinator import OpenAIExtractionCoordinator

    def fake_stream(method, url, headers, json, timeout):
        if url.endswith("/v1/chat/completions"):
            return _FakeStreamResponse(
                ['{"error":{"message":"No available accounts: no available accounts","type":"api_error"}}'],
                content_type="application/json",
                status_code=503,
            )
        return _FakeStreamResponse(
            ["<!doctype html>", "<html><head><title>Sub2API</title></head></html>"],
            content_type="text/html; charset=utf-8",
            status_code=200,
        )

    class FakePostResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        text = "<!doctype html><html><head><title>Sub2API</title></head></html>"

    def fake_post(url, headers, json, timeout):
        if url.endswith("/v1/chat/completions"):
            response = FakePostResponse()
            response.status_code = 503
            response.headers = {"content-type": "application/json"}
            response.text = '{"error":{"message":"No available accounts: no available accounts","type":"api_error"}}'
            return response
        return FakePostResponse()

    monkeypatch.setattr("app.services.agent.llm_client.httpx.stream", fake_stream)
    monkeypatch.setattr("app.services.agent.llm_client.httpx.post", fake_post)

    coordinator = OpenAIExtractionCoordinator({
        "base_url": "https://api.example.test",
        "api_key": "test-key",
        "model": "test-model",
        "api_format": "openai_chat",
        "http_retries": 0,
        "min_request_interval_seconds": 0,
        "allow_root_chat_fallback": True,
    })

    with pytest.raises(RuntimeError) as exc_info:
        coordinator.client.chat_json([{"role": "user", "content": "plan"}], phase="planning")

    message = str(exc_info.value)
    assert "No available accounts" in message
    assert "non-json response" in message
    assert "Expecting value" not in message


def test_openai_coordinator_does_not_probe_root_chat_url_by_default(monkeypatch):
    from app.services.agent.coordinator import OpenAIExtractionCoordinator

    urls = []

    def fake_stream(method, url, headers, json, timeout):
        urls.append(url)
        return _FakeStreamResponse(
            ['{"error":{"message":"Bad gateway","type":"api_error"}}'],
            content_type="application/json",
            status_code=502,
        )

    class FakePostResponse:
        status_code = 502
        headers = {"content-type": "application/json"}
        text = '{"error":{"message":"Bad gateway","type":"api_error"}}'

    def fake_post(url, headers, json, timeout):
        urls.append(url)
        return FakePostResponse()

    monkeypatch.setattr("app.services.agent.llm_client.httpx.stream", fake_stream)
    monkeypatch.setattr("app.services.agent.llm_client.httpx.post", fake_post)

    coordinator = OpenAIExtractionCoordinator({
        "base_url": "https://api.example.test",
        "api_key": "test-key",
        "model": "test-model",
        "api_format": "openai_chat",
        "http_retries": 0,
        "min_request_interval_seconds": 0,
    })

    with pytest.raises(RuntimeError):
        coordinator.client.chat_json([{"role": "user", "content": "plan"}], phase="planning")

    assert urls
    assert all(url == "https://api.example.test/v1/chat/completions" for url in urls)


def test_llm_client_image_data_url_uses_prepared_jpeg(tmp_path):
    from PIL import Image

    from app.services.agent.llm_client import LLMClient

    image_path = tmp_path / "page.png"
    Image.new("RGB", (1200, 900), color=(255, 255, 255)).save(image_path)

    client = LLMClient({
        "api_key": "test-key",
        "force_jpeg_images": True,
        "max_image_side": 500,
        "max_image_bytes": 1,
        "min_request_interval_seconds": 0,
    })

    data_url = client.image_data_url(str(image_path))

    assert data_url is not None
    assert data_url.startswith("data:image/jpeg;base64,")


def test_visual_agent_uses_text_fallback_when_json_visual_call_fails(tmp_path, monkeypatch):
    from PIL import Image

    from app.services.agent.agents import VisualBatchAgent
    from app.services.agent.llm_client import LLMClient
    from app.services.agent.types import ExtractionTask, FigureExtractionPlan, SupervisorState

    image_path = tmp_path / "figure.png"
    Image.new("RGB", (300, 200), color=(255, 255, 255)).save(image_path)
    client = LLMClient({
        "api_key": "test-key",
        "force_jpeg_images": True,
        "min_request_interval_seconds": 0,
    })

    monkeypatch.setattr(client, "chat_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("empty assistant content")))
    monkeypatch.setattr(client, "chat_text", lambda *args, **kwargs: "图中显示柱状图，A组约为10，B组约为20。")

    plan = FigureExtractionPlan(
        figure_id="Figure 1 [asset:1]",
        image_path=str(image_path),
        caption="Bar chart",
        tasks=[ExtractionTask(metric_name="key_metrics", text_context="extract bars")],
    )

    result = VisualBatchAgent(client)._analyze_with_retry(plan, SupervisorState())

    assert result["mode"] == "visual_text_fallback"
    assert result["extractions"][0]["success"] is True
    assert "A组约为10" in result["extractions"][0]["qualitative"]
    assert "结构化视觉 JSON 失败" in result["extractions"][0]["notes"]


def test_visual_agent_uses_text_first_for_page_snapshots(tmp_path, monkeypatch):
    from PIL import Image

    from app.services.agent.agents import VisualBatchAgent
    from app.services.agent.llm_client import LLMClient
    from app.services.agent.types import ExtractionTask, FigureExtractionPlan, SupervisorState

    image_path = tmp_path / "page.png"
    Image.new("RGB", (300, 200), color=(255, 255, 255)).save(image_path)
    client = LLMClient({
        "api_key": "test-key",
        "force_jpeg_images": True,
        "min_request_interval_seconds": 0,
    })

    def fail_json(*args, **kwargs):
        raise AssertionError("page snapshots should not use JSON visual call first")

    monkeypatch.setattr(client, "chat_json", fail_json)
    monkeypatch.setattr(client, "chat_text", lambda *args, **kwargs: "页面截图显示关键趋势。")

    plan = FigureExtractionPlan(
        figure_id="Page 4 Visual Evidence [asset:1]",
        image_path=str(image_path),
        caption="Page-level visual evidence generated from a page containing figure-like content.",
        tasks=[ExtractionTask(metric_name="comprehensive_data_extraction", text_context="extract page")],
    )

    result = VisualBatchAgent(client)._analyze_with_retry(plan, SupervisorState())

    assert result["mode"] == "visual_text_fallback"
    assert result["json_failure_reason"] == "page snapshot uses text-first visual analysis"
    assert result["extractions"][0]["success"] is True


def test_visual_batch_agent_analyzes_multiple_figures_in_parallel(monkeypatch):
    from app.services.agent.agents import VisualBatchAgent
    from app.services.agent.types import ExtractionTask, FigureExtractionPlan, SupervisorState

    monkeypatch.delenv("VISUAL_LLM_MAX_WORKERS", raising=False)
    monkeypatch.setenv("VISUAL_LLM_MAX_RETRIES", "0")

    active = 0
    max_active = 0
    lock = threading.Lock()

    class FakeVisualBatchAgent(VisualBatchAgent):
        def _analyze_figure(self, plan: FigureExtractionPlan) -> dict:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.15)
            with lock:
                active -= 1
            return {
                "figure_id": plan.figure_id,
                "image_path": plan.image_path,
                "extractions": [{"metric": "key_metrics", "success": True, "data": {"ok": True}}],
            }

    plans = [
        FigureExtractionPlan(
            figure_id=f"Figure {index}",
            image_path=f"/tmp/figure-{index}.png",
            caption="figure",
            tasks=[ExtractionTask(metric_name="key_metrics", text_context="extract")],
        )
        for index in range(4)
    ]

    started = time.perf_counter()
    results = FakeVisualBatchAgent(client=object()).analyze_batch(plans, SupervisorState())
    elapsed = time.perf_counter() - started

    assert [result["figure_id"] for result in results] == [plan.figure_id for plan in plans]
    assert max_active > 1
    assert elapsed < 0.45


def test_global_map_agent_routes_deterministically_without_llm():
    from app.services.agent.agents import GlobalMapAgent

    class FailingClient:
        def chat_json(self, *args, **kwargs):
            raise AssertionError("mapping should not call LLM")

    paper = PaperData(
        paper_id="paper-1",
        title="Mesospace domain orchestrates microbial",
        content=(
            "Here we propose a mesospace-domain regulation strategy. "
            "We tailored a novel microbial consortium comprising Clostridium carboxidivorans P7 and "
            "Shewanella oneidensis MR-1. The system was confined within 10–40 μm-diameter hydrogel chambers. "
            "Meso-CS increased hexanoic acid titres to 10,485.8 mg COD l−1."
        ),
        figures=[
            FigureInfo(
                figure_id="Fig. 1 [asset:1]",
                image_path="/tmp/fig.png",
                caption="Fig. 1 schematic illustration of the mesospace domain.",
                context="asset_type=figure; visual_role=figure_candidate",
            )
        ],
    )

    extraction_map, not_found = GlobalMapAgent(FailingClient()).build_map(
        paper,
        ["objective", "materials_methods", "key_metrics", "figure_data"],
    )

    assert not not_found
    assert extraction_map.text_only_metrics
    assert any(item["field"] == "水凝胶微腔直径" for item in extraction_map.text_only_metrics)
    assert "Fig. 1 [asset:1]" in extraction_map.figures
    assert extraction_map.figures["Fig. 1 [asset:1]"].tasks[0].metric_name == "figure_data"


def test_result_mapper_filters_negative_visual_outputs_and_derives_specific_text_fields():
    from app.services.agent.result_mapper import AgentResultMapper

    figure = DocumentAsset(
        id=402,
        document_id=1,
        asset_type="figure",
        file_path="fig1.png",
        metadata_json=json.dumps({"figure_label": "Fig. 1", "caption": "Schematic illustration."}),
    )
    final_results = {
        "text_only_data": [
            {
                "metric": "materials_methods",
                "value": "微生物被限制在直径 10–40 µm 的 hydrogel chambers 中。",
                "evidence": "was confined within 10–40 μm-diameter hydrogel chambers.",
            },
            {
                "metric": "materials_methods",
                "value": "",
                "evidence": "",
            },
        ],
        "by_figure": {
            "Fig. 1 [asset:402]": {
                "figure_type": "molecular_structure",
                "overall_description": "该图是分子结构示意图，没有坐标轴或数值。",
                "extractions": [
                    {
                        "metric": "文字标注",
                        "success": True,
                        "qualitative": "图像内部未见任何文字标签、箭头说明、数值说明或统计标记。",
                        "confidence": "high",
                        "notes": "用户提供的图注包含文字信息，但图像本身没有可见文字。",
                    },
                    {
                        "metric": "可见定量数据",
                        "success": True,
                        "qualitative": "图中没有任何可直接读取的数值数据，因此无法提取柱高、点坐标、线趋势、误差范围或p值。",
                        "confidence": "high",
                    },
                    {
                        "metric": "visible_evidence",
                        "success": True,
                        "qualitative": "中央青色结构占据图像中部，呈现明显三维折叠和螺旋特征。",
                        "confidence": "medium",
                        "evidence": "图中部可见青色三维结构。",
                    },
                ],
            }
        },
        "not_found_metrics": [],
    }

    rows = AgentResultMapper().map_results(job_id=41, final_results=final_results, figures=[figure], tables=[])

    assert [row.field_name for row in rows] == ["水凝胶微腔直径", "可见图像证据"]
    assert all("无法提取" not in row.content for row in rows)
    assert all("没有任何" not in row.content for row in rows)


def test_structured_extraction_hides_existing_negative_visual_rows(client, db, user):
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="negative visual paper",
        original_filename="negative.pdf",
        stored_filename="negative.pdf",
        original_file_path="1/2026/06/negative.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="body",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    figure = DocumentAsset(
        document_id=paper.id,
        asset_type="figure",
        file_path="fig.png",
        mime_type="image/png",
        metadata_json=json.dumps({"figure_label": "Fig. 1", "caption": "Schematic"}),
    )
    db.add(figure)
    db.commit()
    db.refresh(figure)
    job = ExtractionJob(paper_id=paper.id, query="extract", status="done")
    db.add(job)
    db.commit()
    db.refresh(job)
    db.add_all(
        [
            ExtractionResult(
                job_id=job.id,
                source_type="asset",
                source_id=figure.id,
                field_name="可见定量数据",
                content="图中没有任何可直接读取的数值数据，因此无法提取柱高。",
                evidence="schematic",
                confidence=0.85,
                extraction_mode="visual_analysis",
            ),
            ExtractionResult(
                job_id=job.id,
                source_type="asset",
                source_id=figure.id,
                field_name="中央结构",
                content="中央青色结构位于图像中部。",
                evidence="schematic",
                confidence=0.65,
                extraction_mode="visual_analysis",
            ),
        ]
    )
    db.commit()

    response = client.get(f"/extractions/{job.id}/structured")

    assert response.status_code == 200
    figure_results = response.json()["figure_results"]
    assert [item["metric"] for item in figure_results] == ["中央结构"]


def test_structured_extraction_hides_low_confidence_and_localizes_english_text(client, db, user):
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="localized paper",
        original_filename="localized.pdf",
        stored_filename="localized.pdf",
        original_file_path="1/2026/06/localized.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="body",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    job = ExtractionJob(paper_id=paper.id, query="extract", status="done")
    db.add(job)
    db.commit()
    db.refresh(job)
    db.add_all(
        [
            ExtractionResult(
                job_id=job.id,
                source_type="text",
                field_name="mechanistic_conclusion",
                content="The improvement was attributed to porin regulation and exometabolite enrichment that shifted interbacterial interactions from unidirectional electron transfer to bidirectional multimetabolite cross-feeding.",
                evidence="This improvement is attributed to mesospace-governed porin regulation and exometabolite enrichment.",
                confidence=0.7,
                extraction_mode="text_extraction",
            ),
            ExtractionResult(
                job_id=job.id,
                source_type="asset",
                field_name="实验分组",
                content="低置信视觉解释",
                evidence="visual evidence",
                confidence=0.4,
                extraction_mode="visual_analysis",
            ),
        ]
    )
    db.commit()

    response = client.get(f"/extractions/{job.id}/structured")

    assert response.status_code == 200
    payload = response.json()
    assert payload["figure_results"] == []
    assert payload["text_results"][0]["value"].startswith("性能提升归因于孔蛋白调控")
    assert "The improvement" not in payload["text_results"][0]["value"]


def test_parse_generates_page_snapshot_when_pdf_has_no_figures(db, user, tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    from app.core import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    relative_path = "1/2026/05/nofig.pdf"
    pdf_path = tmp_path / relative_path
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "A text-only PDF page for snapshot fallback.")
    pdf.save(str(pdf_path))
    pdf.close()

    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="text only paper",
        original_filename="nofig.pdf",
        stored_filename="nofig.pdf",
        original_file_path=relative_path,
        file_size=pdf_path.stat().st_size,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        error_message="old extraction error",
        fail_reason="old parse reason",
        cleaned_text="A text-only PDF page for snapshot fallback.",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    parsed = PaperDemoService(db).parse(paper)

    assets = db.query(DocumentAsset).filter(DocumentAsset.document_id == paper.id).all()
    assert len(assets) >= 1
    snapshot = next(asset for asset in assets if asset.asset_type == "page_snapshot")
    metadata = json.loads(snapshot.metadata_json)
    assert snapshot.page_number == 1
    assert snapshot.mime_type == "image/png"
    assert metadata["figure_label"] == "Page 1 Snapshot"
    assert metadata["caption"] == "Fallback page snapshot"
    assert metadata["source"] == "fallback_snapshot"
    assert metadata["fallback"] is True
    assert metadata["visual_role"] == "page_evidence"
    assert metadata["context"] == "Generated because no extractable PDF figure was found"
    assert (tmp_path / snapshot.file_path).exists()
    assert parsed.status == "done"
    assert parsed.error_message == "old extraction error"
    assert parsed.fail_reason == "old parse reason"

    events = db.query(DocumentEvent).filter(DocumentEvent.document_id == paper.id).order_by(DocumentEvent.id.asc()).all()
    event_types = [event.event_type for event in events]
    assert "paper_enhancement_done" in event_types
    assert "paper_figures_partial" in event_types
    assert "paper_tables_fallback" not in event_types
    done_event = next(event for event in events if event.event_type == "paper_enhancement_done")
    done_metadata = json.loads(done_event.event_metadata)
    assert done_metadata["figure_count"] == 0
    assert done_metadata["snapshot_count"] == 1
    assert done_metadata["figure_status"] == "partial"
    assert done_metadata["table_status"] == "failed"
    assert done_metadata["table_source"] == "none"


def test_parse_failure_records_event_and_sets_failed_status(db, user, tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="missing paper",
        original_filename="missing.pdf",
        stored_filename="missing.pdf",
        original_file_path="1/2026/05/missing.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        error_message="existing error",
        fail_reason="existing fail reason",
        cleaned_text="existing text",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    with pytest.raises(FileNotFoundError):
        PaperDemoService(db).parse(paper)

    db.refresh(paper)
    assert paper.status == "failed"
    assert "源 PDF 文件不存在" in paper.fail_reason
    assert paper.cleaned_text == "existing text"
    failed_event = db.query(DocumentEvent).filter(DocumentEvent.document_id == paper.id, DocumentEvent.event_type == "paper_enhancement_failed").one()
    assert "源 PDF 文件不存在" in failed_event.message


def test_table_extractor_reports_fallback_candidate_when_pdfplumber_has_no_tables(tmp_path):
    from app.services.paper.models import ParsedPage
    from app.services.paper.table_extractor import TableExtractor

    report = TableExtractor().extract(
        paper_id=42,
        source_path=tmp_path / "missing.pdf",
        pages=[ParsedPage(page_number=3, text="Table 1\nGroup  Yield  Count\nA  10.5  3\nB  20.2  6")],
        existing_text="",
    )

    assert report.status == "fallback"
    assert report.source == "fallback_candidate"
    assert report.tables[0].table_label == "Table 1"
    assert report.tables[0].page == 3


def test_table_extractor_rejects_inline_table_reference_as_fallback_candidate(tmp_path):
    from app.services.paper.models import ParsedPage
    from app.services.paper.table_extractor import TableExtractor

    page_text = """
    Table 1), and were spiked with tetracycline to simulate wastewater conditions.
    The surrounding paragraph continues as ordinary body text with 2 ppm and 20 ppm values.
    """

    report = TableExtractor().extract(
        paper_id=42,
        source_path=tmp_path / "missing.pdf",
        pages=[ParsedPage(page_number=6, text=page_text)],
        existing_text=page_text,
    )

    assert report.tables == []
    assert report.status == "failed"
    assert report.source == "none"


def test_table_extractor_rejects_first_page_metadata_as_fake_table(tmp_path):
    from app.services.paper.models import ParsedPage
    from app.services.paper.table_extractor import TableExtractor

    page_text = """
    Nature Communications | (2026) 17:1234
    Received: 12 July 2025
    Accepted: 3 February 2026
    Check for updates
    DOI: 10.1038/s41467-026-12345-6
    Author information
    Affiliations
    1 Department of Chemical Engineering, Example University, Shanghai 200000, China
    2 Institute of Biology, Example University, Beijing 100000, China
    Correspondence and requests for materials should be addressed to A.B.
    Abstract
    This study reports continuous microbial production over 120 h and 3 cycles.
    """

    report = TableExtractor().extract(
        paper_id=42,
        source_path=tmp_path / "missing.pdf",
        pages=[ParsedPage(page_number=1, text=page_text)],
        existing_text=page_text,
    )

    assert report.tables == []
    assert report.status == "failed"
    assert report.source == "none"
    assert report.message == "No reliable table found in this PDF."


def test_table_extractor_rejects_pdfplumber_body_fragments_without_caption(tmp_path, monkeypatch):
    from app.services.paper import table_extractor as table_module
    from app.services.paper.models import ParsedPage
    from app.services.paper.table_extractor import TableExtractor

    page_text = """
    Nature Communications | (2026) 17:1234
    Received: 12 July 2025
    Accepted: 3 February 2026
    Check for updates
    DOI: 10.1038/s41467-026-12345-6
    Author information and affiliations
    This study reports microbial production across long operating windows.
    The method uses hydrogel chambers and mixed microbial consortia.
    """
    fake_rows = [
        ["Nature Communications", "2026", "17"],
        ["Received:", "Accepted:", "DOI"],
        ["Author information", "Affiliations", "Correspondence"],
        ["This study", "reports microbial", "production"],
    ]

    class FakePage:
        def extract_tables(self, table_settings=None):
            return [fake_rows]

        def extract_text(self):
            return page_text

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakePdfPlumber:
        @staticmethod
        def open(_source_path):
            return FakePdf()

    monkeypatch.setattr(table_module, "pdfplumber", FakePdfPlumber)

    report = TableExtractor().extract(
        paper_id=42,
        source_path=tmp_path / "body-fragments.pdf",
        pages=[ParsedPage(page_number=1, text=page_text)],
        existing_text=page_text,
    )

    assert report.tables == []
    assert report.status == "failed"
    assert report.source == "none"
    assert report.message == "No reliable table found in this PDF."


def test_table_extractor_rejects_pdfplumber_article_headers_and_figure_captions(tmp_path, monkeypatch):
    from app.services.paper import table_extractor as table_module
    from app.services.paper.models import ParsedPage
    from app.services.paper.table_extractor import TableExtractor

    page_text = """
    Article
    https://doi.org/10.1038/s41467-025-58761-y
    The primer sequences are provided in Supplementary Table 1 for reference.
    Fig. 2 | Dual carbon sequestration in photosynthetic living materials.
    d An increase in cell concentration was observed during the experiment.
    """
    fake_rows = [
        ["Article", "https://doi.org/10.1038/s41467-025-58761-y"],
        ["Fig.2|Dualcarbonsequestrationinphotosyntheticlivingmaterials.", "dAnincreaseincellconcentrationwasobserved"],
        ["Downloaded from", "www.nature.com/naturecommunications"],
    ]

    class FakePage:
        def extract_tables(self, table_settings=None):
            return [fake_rows]

        def extract_text(self):
            return page_text

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakePdfPlumber:
        @staticmethod
        def open(_source_path):
            return FakePdf()

    monkeypatch.setattr(table_module, "pdfplumber", FakePdfPlumber)

    report = TableExtractor().extract(
        paper_id=42,
        source_path=tmp_path / "article-header-fragments.pdf",
        pages=[ParsedPage(page_number=2, text=page_text)],
        existing_text=page_text,
    )

    assert report.tables == []
    assert report.status == "failed"
    assert report.source == "none"


def test_table_extractor_rejects_pdfplumber_reference_list_columns(tmp_path, monkeypatch):
    from app.services.paper import table_extractor as table_module
    from app.services.paper.models import ParsedPage
    from app.services.paper.table_extractor import TableExtractor

    page_text = """
    References
    13. Bottan, S. et al. 3D printing of Flinks for biomedical applications.
    35. Lewis, J. A. Direct ink writing of 3D functional materials. Adv. Funct. Mater.
    Data availability
    Data supporting the findings of this work are available from the corresponding author.
    """
    fake_rows = [
        ["13.", "S. Bottan, F. Robotti, P. Jayathissa, A. Hegglin", "35.", "J. A. Lewis, Direct ink writing of 3D functional materials. Adv. Funct. Mater."],
        ["14.", "A. H. Example et al. Biofabrication of hydrogel networks.", "36.", "K. Sample et al. Nature Materials study."],
        ["15.", "Data availability", "37.", "Data supporting the findings of this work are available."],
    ]

    class FakePage:
        def extract_tables(self, table_settings=None):
            return [fake_rows]

        def extract_text(self):
            return page_text

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakePdfPlumber:
        @staticmethod
        def open(_source_path):
            return FakePdf()

    monkeypatch.setattr(table_module, "pdfplumber", FakePdfPlumber)

    report = TableExtractor().extract(
        paper_id=42,
        source_path=tmp_path / "reference-list.pdf",
        pages=[ParsedPage(page_number=9, text=page_text)],
        existing_text=page_text,
    )

    assert report.tables == []
    assert report.status == "failed"
    assert report.source == "none"


def test_table_extractor_accepts_stable_pdfplumber_table_with_numeric_structure(tmp_path, monkeypatch):
    from app.services.paper import table_extractor as table_module
    from app.services.paper.models import ParsedPage
    from app.services.paper.table_extractor import TableExtractor

    page_text = """
    Results
    Table 1. Reactor performance under three operating modes.
    Mode Yield (%) Rate (g/L/day) Duration (day)
    A 65 1.4 10
    B 72 1.8 12
    C 69 1.6 11
    """
    fake_rows = [
        ["Mode", "Yield (%)", "Rate (g/L/day)", "Duration (day)"],
        ["A", "65", "1.4", "10"],
        ["B", "72", "1.8", "12"],
        ["C", "69", "1.6", "11"],
    ]

    class FakePage:
        def extract_tables(self, table_settings=None):
            return [fake_rows]

        def extract_text(self):
            return page_text

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakePdfPlumber:
        @staticmethod
        def open(_source_path):
            return FakePdf()

    monkeypatch.setattr(table_module, "pdfplumber", FakePdfPlumber)

    report = TableExtractor().extract(
        paper_id=42,
        source_path=tmp_path / "real-table.pdf",
        pages=[ParsedPage(page_number=2, text=page_text)],
        existing_text=page_text,
    )

    assert report.status == "success"
    assert report.source == "pdfplumber"
    assert len(report.tables) == 1
    assert report.tables[0].table_label == "Table 1"
    assert "Yield (%)" in report.tables[0].content


def test_table_extractor_reports_weak_partial_only_for_stable_numeric_columns(tmp_path):
    from app.services.paper.models import ParsedPage
    from app.services.paper.table_extractor import TableExtractor

    page_text = """
    Results
    Group      Yield (%)      Rate (g/L/day)
    Control    52             1.1
    Hydrogel   78             2.4
    Reused     73             2.0
    The next paragraph returns to normal prose and should stop the block.
    """

    report = TableExtractor().extract(
        paper_id=42,
        source_path=tmp_path / "missing.pdf",
        pages=[ParsedPage(page_number=3, text=page_text)],
        existing_text=page_text,
    )

    assert report.status == "partial"
    assert report.source == "weak_table_candidate"
    assert len(report.tables) == 1
    assert report.tables[0].table_label == "Detected Table-like Block 1"
    assert "Hydrogel" in report.tables[0].content


def test_figure_extractor_prefers_caption_block_over_body_reference(tmp_path):
    fitz = pytest.importorskip("fitz")
    from app.services.file_storage import FileStorageService
    from app.services.paper.figure_extractor import FigureExtractor
    from app.services.paper.models import ParsedPage

    upload_dir = tmp_path / "uploads"
    source_path = upload_dir / "3" / "paper.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)
    page.insert_text((72, 80), "As shown in Fig. 2A, the reactor response increased after startup.")
    page.draw_rect(fitz.Rect(96, 190, 500, 330), color=(0, 0, 0), width=1)
    page.draw_line((120, 310), (470, 225), color=(0.1, 0.3, 0.8), width=2)
    page.draw_line((120, 280), (470, 250), color=(0.8, 0.2, 0.2), width=2)
    page.insert_text((72, 360), "Fig. 2A Vector kinetics of production rate across operating time.")
    page_text = page.get_text()
    pdf.save(str(source_path))
    pdf.close()

    paper = Document(
        id=77,
        user_id=3,
        title="vector figure paper",
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        original_file_path="3/paper.pdf",
        file_size=source_path.stat().st_size,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        status="done",
    )

    report = FigureExtractor(FileStorageService(str(upload_dir))).extract(
        source_path=source_path,
        paper=paper,
        pages=[ParsedPage(page_number=1, text=page_text)],
    )

    assert report.status == "success"
    assert report.figure_count == 1
    assert report.snapshot_count == 1
    asset = next(item for item in report.assets if item.asset_type == "figure")
    metadata = json.loads(asset.metadata_json)
    assert asset.asset_type == "figure"
    assert asset.page_number == 1
    assert metadata["figure_label"] == "Fig. 2A"
    assert metadata["source"] == "rendered_figure_region"
    assert metadata["fallback"] is False
    assert metadata["visual_role"] == "figure_candidate"
    assert (upload_dir / asset.file_path).exists()
    page_evidence = next(item for item in report.assets if item.asset_type == "page_snapshot")
    page_metadata = json.loads(page_evidence.metadata_json)
    assert page_metadata["source"] == "page_visual_snapshot"
    assert page_metadata["fallback"] is False
    assert page_metadata["visual_role"] == "page_evidence"


def test_figure_extractor_uses_page_visual_snapshot_when_caption_crop_is_text_polluted(tmp_path):
    fitz = pytest.importorskip("fitz")
    from app.services.file_storage import FileStorageService
    from app.services.paper.figure_extractor import FigureExtractor
    from app.services.paper.models import ParsedPage

    upload_dir = tmp_path / "uploads"
    source_path = upload_dir / "4" / "polluted.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)
    y = 72
    for index in range(18):
        page.insert_text(
            (72, y),
            f"Body paragraph line {index + 1} describing methods, results, controls, and discussion text.",
            fontsize=9,
        )
        y += 18
    page.insert_text((72, 470), "Fig. 4 Long caption for a figure-like page where a local crop would mostly contain body text.")
    page_text = page.get_text()
    pdf.save(str(source_path))
    pdf.close()

    paper = Document(
        id=78,
        user_id=4,
        title="text polluted crop paper",
        original_filename="polluted.pdf",
        stored_filename="polluted.pdf",
        original_file_path="4/polluted.pdf",
        file_size=source_path.stat().st_size,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        status="done",
    )

    report = FigureExtractor(FileStorageService(str(upload_dir))).extract(
        source_path=source_path,
        paper=paper,
        pages=[ParsedPage(page_number=1, text=page_text)],
    )

    assert report.status == "partial"
    assert report.figure_count == 0
    assert report.snapshot_count == 1
    assert [asset.asset_type for asset in report.assets] == ["page_snapshot"]
    metadata = json.loads(report.assets[0].metadata_json)
    assert metadata["figure_label"] == "Page 1 Visual Evidence"
    assert metadata["source"] == "page_visual_snapshot"
    assert metadata["fallback"] is False
    assert metadata["visual_role"] == "page_evidence"
    assert "fallback_snapshot" not in metadata["source"]


def test_figure_extractor_keeps_extracted_image_objects_on_rendered_pages(tmp_path):
    fitz = pytest.importorskip("fitz")
    Image = pytest.importorskip("PIL.Image")
    from app.services.file_storage import FileStorageService
    from app.services.paper.figure_extractor import FigureExtractor
    from app.services.paper.models import ParsedPage

    upload_dir = tmp_path / "uploads"
    source_path = upload_dir / "5" / "image-and-rendered.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    image_path = tmp_path / "embedded.png"
    Image.new("RGB", (220, 220), color=(50, 120, 200)).save(image_path)

    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(90, 110, 310, 330), filename=str(image_path))
    page.draw_rect(fitz.Rect(340, 150, 510, 300), color=(0, 0, 0), width=1)
    page.draw_line((360, 280), (490, 185), color=(0.1, 0.2, 0.8), width=2)
    page.insert_text((72, 360), "Fig. 1 Combined raster image and vector line plot on the same PDF page.")
    page_text = page.get_text()
    pdf.save(str(source_path))
    pdf.close()

    paper = Document(
        id=79,
        user_id=5,
        title="image and rendered paper",
        original_filename="image-and-rendered.pdf",
        stored_filename="image-and-rendered.pdf",
        original_file_path="5/image-and-rendered.pdf",
        file_size=source_path.stat().st_size,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        status="done",
    )

    report = FigureExtractor(FileStorageService(str(upload_dir))).extract(
        source_path=source_path,
        paper=paper,
        pages=[ParsedPage(page_number=1, text=page_text)],
    )

    sources = [json.loads(asset.metadata_json)["source"] for asset in report.assets]
    assert "rendered_figure_region" in sources
    assert "extracted_image" in sources
    assert "page_visual_snapshot" in sources
    assert report.figure_count == 2
    assert report.snapshot_count == 1
    image_object = next(asset for asset in report.assets if json.loads(asset.metadata_json)["source"] == "extracted_image")
    assert json.loads(image_object.metadata_json)["visual_role"] == "image_object"


def test_figure_extractor_classifies_rendered_visual_evidence(tmp_path):
    fitz = pytest.importorskip("fitz")
    from app.services.file_storage import FileStorageService
    from app.services.paper.figure_extractor import FigureExtractor
    from app.services.paper.models import ParsedPage

    upload_dir = tmp_path / "uploads"
    source_path = upload_dir / "9" / "chart-region.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)
    page.draw_line((120, 330), (120, 160), color=(0, 0, 0), width=1)
    page.draw_line((120, 330), (480, 330), color=(0, 0, 0), width=1)
    page.draw_line((140, 300), (230, 250), color=(0.1, 0.3, 0.8), width=2)
    page.draw_line((230, 250), (360, 210), color=(0.1, 0.3, 0.8), width=2)
    page.draw_line((360, 210), (460, 180), color=(0.1, 0.3, 0.8), width=2)
    page.insert_text((72, 370), "Fig. 9 Growth chart with axes and time-series trend.")
    page_text = page.get_text()
    pdf.save(str(source_path))
    pdf.close()

    paper = Document(
        id=91,
        user_id=9,
        title="chart region paper",
        original_filename="chart-region.pdf",
        stored_filename="chart-region.pdf",
        original_file_path="9/chart-region.pdf",
        file_size=source_path.stat().st_size,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        status="done",
    )

    report = FigureExtractor(FileStorageService(str(upload_dir))).extract(
        source_path=source_path,
        paper=paper,
        pages=[ParsedPage(page_number=1, text=page_text)],
    )

    asset = next(item for item in report.assets if item.asset_type == "figure")
    metadata = json.loads(asset.metadata_json)
    assert metadata["source"] == "rendered_figure_region"
    assert metadata["evidence_type"] == "chart"
    assert metadata["bbox"]
    assert 0 <= metadata["text_density"] <= 1
    assert metadata["image_density"] > 0
    assert metadata["has_caption"] is True
    assert metadata["has_axis_or_chart_shapes"] is True
    assert metadata["confidence"] >= 0.7


def test_figure_extractor_does_not_promote_captioned_text_region_to_figure(tmp_path):
    fitz = pytest.importorskip("fitz")
    from app.services.file_storage import FileStorageService
    from app.services.paper.figure_extractor import FigureExtractor
    from app.services.paper.models import ParsedPage

    upload_dir = tmp_path / "uploads"
    source_path = upload_dir / "10" / "text-region.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)
    y = 90
    for index in range(14):
        page.insert_text((72, y), f"Dense body text line {index} with methods, values, controls, and discussion.", fontsize=9)
        y += 18
    page.insert_text((72, 390), "Fig. 10 Mentioned in text but no visual figure exists in this region.")
    page_text = page.get_text()
    pdf.save(str(source_path))
    pdf.close()

    paper = Document(
        id=92,
        user_id=10,
        title="text region paper",
        original_filename="text-region.pdf",
        stored_filename="text-region.pdf",
        original_file_path="10/text-region.pdf",
        file_size=source_path.stat().st_size,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        status="done",
    )

    report = FigureExtractor(FileStorageService(str(upload_dir))).extract(
        source_path=source_path,
        paper=paper,
        pages=[ParsedPage(page_number=1, text=page_text)],
    )

    assert not [asset for asset in report.assets if asset.asset_type == "figure"]
    assert all(json.loads(asset.metadata_json)["evidence_type"] != "figure" for asset in report.assets)


def test_figure_extractor_limits_page_visual_snapshots_to_six_pages(tmp_path):
    fitz = pytest.importorskip("fitz")
    from app.services.file_storage import FileStorageService
    from app.services.paper.figure_extractor import FigureExtractor
    from app.services.paper.models import ParsedPage

    upload_dir = tmp_path / "uploads"
    source_path = upload_dir / "6" / "many-visual-pages.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = fitz.open()
    parsed_pages: list[ParsedPage] = []
    for page_index in range(8):
        page = pdf.new_page(width=612, height=792)
        y = 72
        for line_index in range(18):
            page.insert_text((72, y), f"Body line {page_index}-{line_index} with methods and discussion text.", fontsize=9)
            y += 18
        page.insert_text((72, 470), f"Fig. {page_index + 1} Caption for a figure-like page that needs page evidence.")
        parsed_pages.append(ParsedPage(page_number=page_index + 1, text=page.get_text()))
    pdf.save(str(source_path))
    pdf.close()

    paper = Document(
        id=80,
        user_id=6,
        title="many visual pages",
        original_filename="many-visual-pages.pdf",
        stored_filename="many-visual-pages.pdf",
        original_file_path="6/many-visual-pages.pdf",
        file_size=source_path.stat().st_size,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        status="done",
    )

    report = FigureExtractor(FileStorageService(str(upload_dir))).extract(
        source_path=source_path,
        paper=paper,
        pages=parsed_pages,
    )

    assert report.status == "partial"
    assert report.figure_count == 0
    assert report.snapshot_count == 6
    assert len(report.assets) == 6
    assert all(json.loads(asset.metadata_json)["source"] == "page_visual_snapshot" for asset in report.assets)


def test_run_extraction_returns_pending_job_for_polling(client, db, user, monkeypatch):
    scheduled_jobs: list[int] = []
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="sample paper",
        original_filename="sample.pdf",
        stored_filename="sample.pdf",
        original_file_path="1/2026/05/sample.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="hydrogel chambers improved hexanoic acid production.",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    monkeypatch.setattr(
        "app.api.routes.extractions._schedule_job",
        lambda job_id: scheduled_jobs.append(job_id),
    )

    response = client.post("/extractions/run", json={"paperId": paper.id, "query": "提取关键指标"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["error_message"] is None
    assert scheduled_jobs == [payload["id"]]

    list_response = client.get(f"/extractions?paper_id={paper.id}")
    assert list_response.status_code == 200
    jobs = list_response.json()
    assert jobs[0]["id"] == payload["id"]
    assert jobs[0]["status"] == "pending"
    assert jobs[0]["result_count"] == 0


def test_extraction_queue_payload_round_trip():
    from app.queue.extraction_queue import build_extraction_payload, parse_extraction_payload

    payload = build_extraction_payload(42)

    assert parse_extraction_payload(payload) == 42
    assert parse_extraction_payload('{"type": "document_parse", "job_id": 42}') is None
    assert parse_extraction_payload('{"type": "extraction_run", "job_id": "42"}') is None


def test_enqueue_extraction_uses_dedicated_queue(monkeypatch):
    import app.queue.extraction_queue as extraction_queue

    calls: list[tuple[str, str]] = []

    class FakeRedisQueue:
        def __init__(self, queue_name: str) -> None:
            self.queue_name = queue_name

        def enqueue(self, payload: str) -> None:
            calls.append((self.queue_name, payload))

    monkeypatch.setattr(extraction_queue, "RedisQueue", FakeRedisQueue)

    extraction_queue.enqueue_extraction(7)

    assert len(calls) == 1
    queue_name, payload = calls[0]
    assert queue_name == extraction_queue.EXTRACTION_QUEUE_NAME
    assert extraction_queue.parse_extraction_payload(payload) == 7


def test_extraction_metrics_reports_queue_and_status_counts(client, db, user, monkeypatch):
    import app.api.routes.extractions as extraction_routes

    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="metrics paper",
        original_filename="metrics.pdf",
        stored_filename="metrics.pdf",
        original_file_path="1/2026/06/metrics.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="metrics content",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    db.add_all(
        [
            ExtractionJob(paper_id=paper.id, query="pending", status="pending", created_at=now, updated_at=now),
            ExtractionJob(paper_id=paper.id, query="done", status="done", created_at=now, updated_at=now),
            ExtractionJob(paper_id=paper.id, query="failed", status="failed", created_at=now, updated_at=now),
            DocumentAsset(document_id=paper.id, asset_type="figure", file_path="figure.png", mime_type="image/png"),
        ]
    )
    db.commit()

    class FakeRedisQueue:
        def __init__(self, queue_name: str) -> None:
            self.queue_name = queue_name

        def size(self) -> int:
            assert self.queue_name == extraction_routes.EXTRACTION_QUEUE_NAME
            return 5

    monkeypatch.setattr(extraction_routes, "RedisQueue", FakeRedisQueue)

    response = client.get("/extractions/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["queue_name"] == extraction_routes.EXTRACTION_QUEUE_NAME
    assert payload["queue_size"] == 5
    assert payload["pending_jobs"] == 1
    assert payload["done_jobs"] == 1
    assert payload["failed_jobs"] == 1
    assert payload["success_rate"] == 50.0
    assert payload["active_figure_count"] == 1


def test_run_extraction_job_records_phase_events(db, user, monkeypatch):
    from app.services import extraction_job_service

    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="phase paper",
        original_filename="phase.pdf",
        stored_filename="phase.pdf",
        original_file_path="1/2026/06/phase.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="phase content",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    job = ExtractionJob(paper_id=paper.id, query="提取阶段", status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    class FakePaperDataAdapter:
        def build(self, paper, figures, tables):
            return {"paper_id": paper.id}

    class FakeCoordinatorAdapter:
        def run(self, *, paper, user_query, on_event=None):
            events = [
                {"phase": "PLANNING", "status": "start", "message": "规划中"},
                {"phase": "MAPPING", "status": "done", "message": "映射完成"},
                {"phase": "VISUAL_ANALYSIS", "status": "start", "message": "分析 2 张图片", "data": {"figure_count": 2}},
                {"phase": "VISUAL_ANALYSIS", "status": "figure_done", "message": "Figure 1 完成"},
                {"phase": "RESULT_REFLECTION", "status": "done", "message": "复核完成"},
                {"phase": "FINISH", "status": "done", "message": "完成", "results": {"ok": True}},
            ]
            for event in events:
                if on_event:
                    on_event(event)
            return {"ok": True}, events

    class FakeResultMapper:
        def map_results(self, job_id, final_results, figures, tables):
            return [
                ExtractionResult(
                    job_id=job_id,
                    source_type="text",
                    field_name="summary",
                    content="done",
                    evidence="phase content",
                )
            ]

    monkeypatch.setattr(extraction_job_service, "PaperDataAdapter", FakePaperDataAdapter)
    monkeypatch.setattr(extraction_job_service, "CoordinatorAdapter", FakeCoordinatorAdapter)
    monkeypatch.setattr(extraction_job_service, "AgentResultMapper", FakeResultMapper)

    extraction_job_service.run_extraction_job(db, job, paper)

    db.refresh(job)
    assert job.status == "done"
    events = (
        db.query(DocumentEvent)
        .filter(DocumentEvent.document_id == paper.id, DocumentEvent.event_type == "extraction_phase")
        .order_by(DocumentEvent.id.asc())
        .all()
    )
    phases = [json.loads(event.event_metadata)["phase"] for event in events]
    assert phases == ["PLANNING", "MAPPING", "VISUAL_ANALYSIS", "VISUAL_ANALYSIS", "RESULT_REFLECTION", "FINISH"]
    visual_done = json.loads(events[3].event_metadata)
    assert visual_done["job_id"] == job.id
    assert visual_done["figures_done"] == 1
    assert visual_done["figures_total"] == 2


def test_list_extractions_returns_phase_progress(client, db, user):
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="progress paper",
        original_filename="progress.pdf",
        stored_filename="progress.pdf",
        original_file_path="1/2026/06/progress.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="progress content",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    job = ExtractionJob(paper_id=paper.id, query="progress", status="running", created_at=now, updated_at=now)
    db.add(job)
    db.commit()
    db.refresh(job)
    db.add_all(
        [
            DocumentEvent(
                document_id=paper.id,
                user_id=user.id,
                event_type="extraction_phase",
                message="阶段3: 并行分析 4 张图片...",
                event_metadata=json.dumps(
                    {
                        "job_id": job.id,
                        "phase": "VISUAL_ANALYSIS",
                        "status": "start",
                        "message": "阶段3: 并行分析 4 张图片...",
                        "figures_total": 4,
                        "figures_done": 0,
                    },
                    ensure_ascii=False,
                ),
                created_at=now,
            ),
            DocumentEvent(
                document_id=paper.id,
                user_id=user.id,
                event_type="extraction_phase",
                message="Figure 2 分析完成",
                event_metadata=json.dumps(
                    {
                        "job_id": job.id,
                        "phase": "VISUAL_ANALYSIS",
                        "status": "figure_done",
                        "message": "Figure 2 分析完成",
                        "figures_total": 4,
                        "figures_done": 2,
                    },
                    ensure_ascii=False,
                ),
                created_at=now,
            ),
        ]
    )
    db.commit()

    response = client.get(f"/extractions?paper_id={paper.id}")

    assert response.status_code == 200
    progress = response.json()[0]["progress"]
    assert progress["phase"] == "VISUAL_ANALYSIS"
    assert progress["phase_label"] == "视觉分析"
    assert progress["status"] == "figure_done"
    assert progress["percent"] == 60
    assert progress["figures_done"] == 2
    assert progress["figures_total"] == 4


def test_paper_detail_returns_snapshot_asset_and_table_metadata(client, db, user):
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="asset rich paper",
        original_filename="asset.pdf",
        stored_filename="asset.pdf",
        original_file_path="1/2026/05/asset.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        error_message="old extraction failure",
        cleaned_text="paper body",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    db.add_all(
        [
            DocumentAsset(
                document_id=paper.id,
                asset_type="figure",
                page_number=2,
                file_path="1/paper_agent/asset/figure.png",
                mime_type="image/png",
                metadata_json='{"figure_label":"Figure 1","caption":"A real PDF image","source":"extracted_image","fallback":false}',
            ),
            DocumentAsset(
                document_id=paper.id,
                asset_type="page_snapshot",
                page_number=1,
                file_path="1/paper_agent/asset/page_1_snapshot.png",
                mime_type="image/png",
                metadata_json=(
                    '{"figure_label":"Page 1 Snapshot","caption":"Fallback page snapshot",'
                    '"source":"fallback_snapshot","fallback":true,"context":"Generated because no extractable PDF figure was found"}'
                ),
            ),
            DocumentAsset(
                document_id=paper.id,
                asset_type="page_snapshot",
                page_number=2,
                file_path="1/paper_agent/asset/page_2_visual_snapshot.png",
                mime_type="image/png",
                metadata_json=(
                    '{"figure_label":"Page 2 Visual Evidence",'
                    '"caption":"Page-level visual evidence generated from a page containing figure-like content.",'
                    '"source":"page_visual_snapshot","fallback":false,"visual_role":"page_evidence",'
                    '"context":"Fig. 2 Page-level visual context"}'
                ),
            ),
        ]
    )
    db.add_all(
        [
            DocumentAsset(
                document_id=paper.id,
                asset_type="table",
                asset_index=0,
                label="Table 1",
                caption="Table 1",
                markdown="| A | B |\n| --- | --- |\n| 1 | 2 |",
                page_number=2,
                summary="A/B values.",
                metadata_json='{"key_findings":["1 | 2"]}',
            ),
            DocumentAsset(
                document_id=paper.id,
                asset_type="table",
                asset_index=1,
                label="Table 2",
                caption="Table 2",
                markdown="Table 2\nA  B\nfallback  row",
                page_number=3,
                summary="Fallback table text.",
                metadata_json='{"key_findings":["fallback row"]}',
            ),
            DocumentAsset(
                document_id=paper.id,
                asset_type="table",
                asset_index=2,
                label="Detected block",
                caption="Detected block",
                markdown="plain text candidate",
                page_number=4,
                summary="Plain text candidate.",
                metadata_json='{"key_findings":[]}',
            ),
        ]
    )
    db.commit()

    response = client.get(f"/papers/{paper.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["parse_error"] is None
    figures = {figure["source"]: figure for figure in payload["figures"]}
    assert figures["extracted_image"]["figure_label"] == "Figure 1"
    assert figures["extracted_image"]["fallback"] is False
    assert figures["extracted_image"]["visual_role"] == "image_object"
    assert "fallback_snapshot" not in figures
    assert figures["page_visual_snapshot"]["figure_label"] == "Page 2 Visual Evidence"
    assert figures["page_visual_snapshot"]["fallback"] is False
    assert figures["page_visual_snapshot"]["visual_role"] == "page_evidence"

    tables = {table["table_label"]: table for table in payload["tables"]}
    assert tables["Table 1"]["parse_status"] == "success"
    assert tables["Table 1"]["source"] == "document_asset"
    assert tables["Table 2"]["parse_status"] == "partial"
    assert tables["Table 2"]["source"] == "document_asset"
    assert tables["Detected block"]["parse_status"] == "partial"
    assert tables["Detected block"]["source"] == "document_asset"


def test_paper_data_adapter_keeps_page_snapshot_as_fallback_visual_evidence(db, user, tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="snapshot paper",
        original_filename="snapshot.pdf",
        stored_filename="snapshot.pdf",
        original_file_path="1/2026/05/snapshot.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="body",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    asset = DocumentAsset(
        document_id=paper.id,
        asset_type="page_snapshot",
        page_number=1,
        file_path="1/paper_agent/snapshot/page-1-snapshot.png",
        mime_type="image/png",
        metadata_json=(
            '{"figure_label":"Page 1 Snapshot","caption":"Fallback page snapshot",'
            '"source":"fallback_snapshot","fallback":true,"visual_role":"fallback_snapshot",'
            '"context":"Generated because no extractable PDF figure was found"}'
        ),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    paper_data = PaperDataAdapter().build(paper=paper, figures=[asset], tables=[])

    assert paper_data.figures[0].figure_id == f"Page 1 Snapshot [asset:{asset.id}]"
    assert paper_data.figures[0].caption == "Fallback page snapshot"
    assert paper_data.figures[0].context == (
        "Generated because no extractable PDF figure was found\n"
        "Fallback snapshot; lowest-priority visual evidence.\n"
        "asset_type=page_snapshot; source=fallback_snapshot; fallback=True; visual_role=fallback_snapshot; "
        "page_number=1; figure_label=Page 1 Snapshot; caption=Fallback page snapshot"
    )


def test_paper_data_adapter_explains_page_evidence_and_image_object_roles(db, user, tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="visual role paper",
        original_filename="visual.pdf",
        stored_filename="visual.pdf",
        original_file_path="1/2026/05/visual.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="body",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    image_asset = DocumentAsset(
        document_id=paper.id,
        asset_type="figure",
        page_number=2,
        file_path="1/paper_agent/visual/image-object.png",
        mime_type="image/png",
        metadata_json='{"figure_label":"Figure 2 image","caption":"Image object","source":"extracted_image","fallback":false}',
    )
    page_asset = DocumentAsset(
        document_id=paper.id,
        asset_type="page_snapshot",
        page_number=2,
        file_path="1/paper_agent/visual/page-2.png",
        mime_type="image/png",
        metadata_json=(
            '{"figure_label":"Page 2 Visual Evidence","caption":"Page-level visual evidence",'
            '"source":"page_visual_snapshot","fallback":false,"visual_role":"page_evidence",'
            '"context":"Fig. 2 page context"}'
        ),
    )
    db.add_all([image_asset, page_asset])
    db.commit()
    db.refresh(image_asset)
    db.refresh(page_asset)

    paper_data = PaperDataAdapter().build(paper=paper, figures=[image_asset, page_asset], tables=[])

    assert "visual_role=image_object" in paper_data.figures[0].context
    assert "PDF image object; it may be a figure panel or image fragment." in paper_data.figures[0].context
    assert "page_number=2" in paper_data.figures[0].context
    assert "figure_label=Figure 2 image" in paper_data.figures[0].context
    assert "caption=Image object" in paper_data.figures[0].context
    assert "visual_role=page_evidence" in paper_data.figures[1].context
    assert "Page-level visual evidence; not a complete figure." in paper_data.figures[1].context


def test_paper_data_adapter_explains_rendered_figure_candidate(db, user, tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="rendered candidate paper",
        original_filename="rendered.pdf",
        stored_filename="rendered.pdf",
        original_file_path="1/2026/05/rendered.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="body",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    asset = DocumentAsset(
        document_id=paper.id,
        asset_type="figure",
        page_number=4,
        file_path="1/paper_agent/rendered/fig-4.png",
        mime_type="image/png",
        metadata_json=(
            '{"figure_label":"Fig. 4","caption":"Fig. 4 Rendered crop caption.",'
            '"source":"rendered_figure_region","fallback":false,"visual_role":"figure_candidate",'
            '"context":"Fig. 4 Rendered crop caption."}'
        ),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    paper_data = PaperDataAdapter().build(paper=paper, figures=[asset], tables=[])

    assert "visual_role=figure_candidate" in paper_data.figures[0].context
    assert "Figure candidate produced from caption-guided page crop." in paper_data.figures[0].context
    assert "page_number=4" in paper_data.figures[0].context
    assert "figure_label=Fig. 4" in paper_data.figures[0].context
    assert "caption=Fig. 4 Rendered crop caption." in paper_data.figures[0].context


def test_frontend_paper_pages_match_five_page_product_shape():
    detail_source = Path("frontend/src/pages/PaperDetailPage.tsx").read_text(encoding="utf-8")
    upload_source = Path("frontend/src/pages/PaperUploadPage.tsx").read_text(encoding="utf-8")
    list_source = Path("frontend/src/pages/PapersPage.tsx").read_text(encoding="utf-8")
    task_source = Path("frontend/src/pages/ExtractionsPage.tsx").read_text(encoding="utf-8")
    result_source = Path("frontend/src/pages/PaperExtractionResultPage.tsx").read_text(encoding="utf-8")

    assert "文件过大" in upload_source
    assert "仅支持 PDF 文件" in upload_source
    assert "请先登录后再上传论文" in upload_source
    assert "MAX_PDF_SIZE_BYTES = 100 * 1024 * 1024" in upload_source

    assert "上传时间" in list_source
    assert "资产" in list_source
    assert "parse_error" in list_source

    assert "基本信息" in detail_source
    assert "正文预览" in detail_source
    assert "图片列表" in detail_source
    assert "表格列表" in detail_source
    assert "操作日志" in detail_source

    assert "提取目标" in task_source
    assert "选择论文" in task_source
    assert "selectedIds" in task_source
    assert "开始提取" in task_source

    assert "图片/图表" in result_source or "图片/图表分析" in result_source
    assert "表格" in result_source
    assert "正文" in result_source
    assert "原始 JSON" in result_source or "JSON" in result_source
    assert "confidence" in result_source or "置信" in result_source
    assert "无预览" in result_source or "无法预览" in result_source
    assert "StructuredExtractionResponse" in result_source or "figure_results" in result_source


def test_list_extractions_without_paper_id_returns_all_user_jobs(client, db, user):
    now = datetime.now(timezone.utc)
    other_user = User(email="other@example.com", username="otheruser", hashed_password=None)
    db.add(other_user)
    db.commit()
    db.refresh(other_user)

    first_paper = Document(
        user_id=user.id,
        title="first paper",
        original_filename="first.pdf",
        stored_filename="first.pdf",
        original_file_path="1/2026/05/first.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="first",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    second_paper = Document(
        user_id=user.id,
        title="second paper",
        original_filename="second.pdf",
        stored_filename="second.pdf",
        original_file_path="1/2026/05/second.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="second",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    other_paper = Document(
        user_id=other_user.id,
        title="other paper",
        original_filename="other.pdf",
        stored_filename="other.pdf",
        original_file_path="2/2026/05/other.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="other",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add_all([first_paper, second_paper, other_paper])
    db.commit()
    db.refresh(first_paper)
    db.refresh(second_paper)
    db.refresh(other_paper)

    first_job = ExtractionJob(paper_id=first_paper.id, query="first query", status="done")
    second_job = ExtractionJob(paper_id=second_paper.id, query="second query", status="failed", error_message="bad extraction")
    other_job = ExtractionJob(paper_id=other_paper.id, query="other query", status="done")
    db.add_all([first_job, second_job, other_job])
    db.commit()
    db.refresh(first_job)
    db.refresh(second_job)
    db.add(
        ExtractionResult(
            job_id=first_job.id,
            source_type="text",
            source_id=None,
            field_name="key_metrics",
            content="result",
            evidence="evidence",
            confidence=0.7,
        )
    )
    db.commit()

    response = client.get("/extractions")

    assert response.status_code == 200
    payload = response.json()
    assert {job["paper_title"] for job in payload} == {"first paper", "second paper"}
    first_payload = next(job for job in payload if job["paper_title"] == "first paper")
    second_payload = next(job for job in payload if job["paper_title"] == "second paper")
    assert first_payload["query"] == "first query"
    assert first_payload["result_count"] == 1
    assert second_payload["status"] == "failed"
    assert second_payload["error_message"] == "bad extraction"


def test_get_extraction_enriches_result_evidence_type_and_preview_urls(client, db, user):
    now = datetime.now(timezone.utc)
    paper = Document(
        user_id=user.id,
        title="visual evidence paper",
        original_filename="visual.pdf",
        stored_filename="visual.pdf",
        original_file_path="1/2026/05/visual.pdf",
        file_size=100,
        mime_type="application/pdf",
        source_type="pdf",
        processing_mode="auto",
        processing_strategy="pdf_text",
        status="done",
        cleaned_text="body",
        created_at=now,
        updated_at=now,
        uploaded_at=now,
        parsed_at=now,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    figure = DocumentAsset(
        document_id=paper.id,
        asset_type="figure",
        page_number=2,
        file_path="1/paper_agent/visual/fig.png",
        mime_type="image/png",
        metadata_json=json.dumps(
            {
                "figure_label": "Fig. 2",
                "caption": "Fig. 2 chart caption.",
                "source": "rendered_figure_region",
                "evidence_type": "chart",
                "bbox": [10, 20, 300, 220],
                "confidence": 0.82,
            }
        ),
    )
    page_region = DocumentAsset(
        document_id=paper.id,
        asset_type="page_snapshot",
        page_number=3,
        file_path="1/paper_agent/visual/page-3.png",
        mime_type="image/png",
        metadata_json=json.dumps(
            {
                "figure_label": "Page 3 Visual Evidence",
                "caption": "Page-level crop",
                "source": "page_visual_snapshot",
                "evidence_type": "page_region",
            }
        ),
    )
    db.add_all([figure, page_region])
    db.commit()
    db.refresh(figure)
    db.refresh(page_region)

    job = ExtractionJob(paper_id=paper.id, query="extract visuals", status="done")
    db.add(job)
    db.commit()
    db.refresh(job)
    db.add_all(
        [
            ExtractionResult(
                job_id=job.id,
                source_type="asset",
                source_id=figure.id,
                field_name="trend",
                content="increased",
                evidence="Fig. 2",
                confidence=0.8,
            ),
            ExtractionResult(
                job_id=job.id,
                source_type="asset",
                source_id=page_region.id,
                field_name="page_context",
                content="context",
                evidence="page 3",
                confidence=0.4,
            ),
            ExtractionResult(
                job_id=job.id,
                source_type="text",
                source_id=None,
                field_name="abstract_claim",
                content="text finding",
                evidence="abstract text",
                confidence=0.7,
            ),
        ]
    )
    db.commit()

    response = client.get(f"/extractions/{job.id}")

    assert response.status_code == 200
    results = response.json()["results"]
    by_field = {item["field_name"]: item for item in results}
    assert by_field["trend"]["evidence_type"] == "chart"
    assert by_field["trend"]["image_url"] == f"/papers/assets/{figure.id}"
    assert by_field["trend"]["thumbnail_url"] == f"/papers/assets/{figure.id}"
    assert by_field["trend"]["bbox"] == [10, 20, 300, 220]
    assert by_field["trend"]["page"] == 2
    assert by_field["trend"]["caption"] == "Fig. 2 chart caption."
    assert "page_context" not in by_field
    assert by_field["abstract_claim"]["evidence_type"] == "text"
