from __future__ import annotations

import csv
import json
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Document, DocumentAsset, DocumentEvent, ExtractionEvidence, ExtractionItem, ExtractionJob, ExtractionResult, ExtractionRun
from app.schemas.paper import ExtractionJobListItem, ExtractionJobRead, ExtractionResultRead, PaperFigureAsset, StructuredExtractionResponse, StructuredFigureResult, StructuredTableResult, StructuredTextResult
from app.services.extraction.constants import EXTRACTION_PHASE_EVENT, PHASE_BASE_PERCENT, PHASE_LABELS
from app.services.extraction.formatters import confidence_label, display_field_name, is_negative_result_text, legacy_localized_value
from app.services.file_storage import FileStorageService
from app.services.paper.coordinate_preview import coordinate_preview_read, is_coordinate_asset
from app.services.paper.evidence import asset_bbox, asset_image_url, asset_metadata, normalize_evidence_type
from app.services.paper.visual_assets import display_visual_assets
from app.utils.json import json_loads_object_or_empty


@dataclass
class ExtractionJobBundle:
    job: ExtractionJob
    run: ExtractionRun | None
    paper: Document


def _should_hide_legacy_result(result: ExtractionResult) -> bool:
    if result.extraction_mode == "not_found":
        return False
    if result.confidence is not None and result.confidence < 0.5:
        return True
    if result.source_type in {"asset", "figure", "chart"} or result.figure_id:
        return is_negative_result_text(result.content) or is_negative_result_text(result.notes)
    return not (result.content or "").strip() or not (result.evidence or "").strip() or is_negative_result_text(result.content)


def _phase_percent(metadata: dict, job: ExtractionJob) -> int:
    if job.status == "done":
        return 100
    phase = str(metadata.get("phase") or "").upper()
    if phase == "VISUAL_ANALYSIS":
        base = 45
        total = int(metadata.get("figures_total") or 0)
        done = int(metadata.get("figures_done") or 0)
        if total > 0:
            return min(75, base + round((min(done, total) / total) * 30))
        return base
    return int(PHASE_BASE_PERCENT.get(phase, 0 if job.status == "pending" else 10))


def _progress_for_job(job: ExtractionJob, event: DocumentEvent | None) -> dict:
    metadata = json_loads_object_or_empty(event.event_metadata if event else None)
    phase = str(metadata.get("phase") or ("FINISH" if job.status == "done" else "")).upper()
    if job.status == "pending":
        phase = phase or "PENDING"
        percent = 0
    else:
        percent = _phase_percent(metadata, job)
    status_value = "failed" if job.status == "failed" else str(metadata.get("status") or job.status)
    if job.status == "failed" and not phase:
        phase = "FAILED"
        percent = 0
    phase_label = PHASE_LABELS.get(phase, "等待开始" if job.status == "pending" else "提取失败" if job.status == "failed" else "处理中")
    return {
        "phase": phase,
        "phase_label": phase_label,
        "status": status_value,
        "percent": percent,
        "message": str(metadata.get("message") or job.error_message or phase_label),
        "updated_at": event.created_at if event else job.updated_at,
        "figures_done": int(metadata.get("figures_done") or 0),
        "figures_total": int(metadata.get("figures_total") or 0),
    }


class ExtractionReadService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_job_bundle(self, job_id: int) -> ExtractionJobBundle | None:
        job = self.db.get(ExtractionJob, job_id)
        if job is None:
            return None
        paper = self.db.get(Document, job.paper_id)
        if paper is None:
            return None
        run = (
            self.db.query(ExtractionRun)
            .filter(ExtractionRun.legacy_job_id == job.id)
            .order_by(ExtractionRun.id.desc())
            .first()
        )
        return ExtractionJobBundle(job=job, run=run, paper=paper)

    def list_jobs(self, *, user_id: int, paper_id: int | None = None) -> list[ExtractionJobListItem]:
        query = (
            self.db.query(ExtractionJob, Document)
            .join(Document, ExtractionJob.paper_id == Document.id)
            .filter(Document.user_id == user_id, Document.source_type == "pdf", Document.is_deleted == False)
        )
        if paper_id is not None:
            query = query.filter(ExtractionJob.paper_id == paper_id)
        rows = query.order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.desc()).all()
        progress_events = self._latest_progress_events([job for job, _paper in rows])
        run_counts = self._run_item_counts([job.id for job, _paper in rows])

        items: list[ExtractionJobListItem] = []
        for job, paper in rows:
            result_count = run_counts.get(job.id, len(job.results))
            items.append(
                ExtractionJobListItem(
                    id=job.id,
                    paper_id=paper.id,
                    paper_title=paper.title,
                    query=job.query,
                    status=job.status,
                    error_message=job.error_message,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    result_count=result_count,
                    progress=_progress_for_job(job, progress_events.get(job.id)),
                )
            )
        return items

    def get_job_read(self, bundle: ExtractionJobBundle) -> ExtractionJobRead:
        if bundle.run is not None:
            return self._run_job_read(bundle)
        return self._legacy_job_read(bundle.job)

    def get_structured_extraction(self, bundle: ExtractionJobBundle) -> StructuredExtractionResponse:
        if bundle.run is not None:
            return self._run_structured(bundle)
        return self._legacy_structured(bundle)

    def _run_item_counts(self, job_ids: list[int]) -> dict[int, int]:
        if not job_ids:
            return {}
        rows = (
            self.db.query(ExtractionRun.legacy_job_id, func.count(ExtractionItem.id))
            .join(ExtractionItem, ExtractionItem.run_id == ExtractionRun.id)
            .filter(ExtractionRun.legacy_job_id.in_(job_ids))
            .group_by(ExtractionRun.legacy_job_id)
            .all()
        )
        return {int(job_id): int(count) for job_id, count in rows if job_id is not None}

    def _latest_progress_events(self, jobs: list[ExtractionJob]) -> dict[int, DocumentEvent]:
        job_ids = {job.id for job in jobs}
        if not job_ids:
            return {}
        document_ids = {job.paper_id for job in jobs}
        events = (
            self.db.query(DocumentEvent)
            .filter(DocumentEvent.document_id.in_(document_ids), DocumentEvent.event_type == EXTRACTION_PHASE_EVENT)
            .order_by(DocumentEvent.created_at.asc(), DocumentEvent.id.asc())
            .all()
        )
        latest: dict[int, DocumentEvent] = {}
        for event in events:
            job_id = json_loads_object_or_empty(event.event_metadata).get("job_id")
            if isinstance(job_id, int) and job_id in job_ids:
                latest[job_id] = event
        return latest

    def _progress_for_job(self, job: ExtractionJob) -> dict:
        return _progress_for_job(job, self._latest_progress_events([job]).get(job.id))

    @staticmethod
    def legacy_localized_value(metric: str, text: str) -> str:
        return legacy_localized_value(metric, text)

    def _legacy_job_read(self, job: ExtractionJob) -> ExtractionJobRead:
        results = [result for result in sorted(job.results, key=lambda row: row.id) if not _should_hide_legacy_result(result)]
        asset_ids = sorted({result.source_id for result in results if result.source_id is not None and result.source_type in {"asset", "figure", "table"}})
        assets_by_id: dict[int, DocumentAsset] = {}
        if asset_ids:
            assets = self.db.query(DocumentAsset).filter(DocumentAsset.id.in_(asset_ids)).all()
            assets_by_id = {asset.id: asset for asset in assets}
        payload = []
        for result in results:
            asset = assets_by_id.get(result.source_id) if result.source_id is not None else None
            metadata = asset_metadata(asset)
            evidence_type = normalize_evidence_type(source_type=result.source_type, asset=asset, metadata=metadata)
            image_url = asset_image_url(asset)
            caption = result.caption or (str(metadata.get("caption") or "") if asset is not None else None) or (asset.caption if asset is not None else None)
            source = None
            if asset is not None:
                source = str(metadata.get("figure_label") or result.figure_id or asset.asset_type) or None
            payload.append(
                ExtractionResultRead(
                    id=result.id,
                    job_id=result.job_id,
                    source_type=result.source_type,
                    source_id=result.source_id,
                    field_name=display_field_name(result.field_name, result.source_type, result.figure_id),
                    content=result.content or "",
                    evidence=result.evidence,
                    confidence=result.confidence,
                    evidence_type=evidence_type,
                    image_url=image_url,
                    thumbnail_url=image_url,
                    page=asset.page_number if asset is not None else None,
                    bbox=asset_bbox(metadata),
                    caption=caption,
                    source=source,
                    figure_id=result.figure_id,
                    notes=result.notes,
                    structured_data=result.structured_data,
                    parse_status=result.parse_status,
                    extraction_mode=result.extraction_mode,
                    created_at=result.created_at,
                )
            )
        return ExtractionJobRead(
            id=job.id,
            paper_id=job.paper_id,
            query=job.query,
            status=job.status,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            results=payload,
            progress=self._progress_for_job(job),
        )

    def _run_job_read(self, bundle: ExtractionJobBundle) -> ExtractionJobRead:
        assert bundle.run is not None
        items = (
            self.db.query(ExtractionItem)
            .filter(ExtractionItem.run_id == bundle.run.id)
            .order_by(ExtractionItem.id.asc())
            .all()
        )
        evidence_rows = (
            self.db.query(ExtractionEvidence)
            .filter(ExtractionEvidence.item_id.in_([item.id for item in items]))
            .order_by(ExtractionEvidence.id.asc())
            .all()
            if items
            else []
        )
        evidence_by_item: dict[int, list[ExtractionEvidence]] = {}
        asset_ids: set[int] = set()
        for evidence in evidence_rows:
            evidence_by_item.setdefault(evidence.item_id, []).append(evidence)
            if evidence.source_id and evidence.source_type in {"figure", "table"}:
                asset_ids.add(evidence.source_id)
        assets_by_id: dict[int, DocumentAsset] = {}
        if asset_ids:
            assets = self.db.query(DocumentAsset).filter(DocumentAsset.id.in_(sorted(asset_ids))).all()
            assets_by_id = {asset.id: asset for asset in assets}

        results: list[ExtractionResultRead] = []
        for item in items:
            evidences = evidence_by_item.get(item.id, [])
            primary_evidence = evidences[0] if evidences else None
            asset = assets_by_id.get(primary_evidence.source_id) if primary_evidence and primary_evidence.source_id else None
            metadata = asset_metadata(asset)
            evidence_type = normalize_evidence_type(source_type=item.source_type, asset=asset, metadata=metadata)
            image_url = asset_image_url(asset)
            evidence_text = primary_evidence.excerpt if primary_evidence and primary_evidence.excerpt else (primary_evidence.excerpt_context if primary_evidence else "")
            if not evidence_text and item.verification_notes:
                evidence_text = item.verification_notes
            figure_id = item.figure_label or (primary_evidence.source_label if primary_evidence else None)
            structured_data = None
            if item.data_points_json:
                structured_data = json.dumps(
                    {
                        "x_axis": {"label": item.x_axis_label, "unit": item.x_axis_unit, "scale": item.x_axis_scale},
                        "y_axis": {"label": item.y_axis_label, "unit": item.y_axis_unit, "scale": item.y_axis_scale},
                        "series": item.series_name,
                        "data_points": item.data_points_json,
                    },
                    ensure_ascii=False,
                )
            results.append(
                ExtractionResultRead(
                    id=item.id,
                    job_id=bundle.job.id,
                    source_type="asset" if asset is not None else item.source_type,
                    source_id=asset.id if asset is not None else (primary_evidence.source_id if primary_evidence else None),
                    field_name=display_field_name(item.indicator, item.source_type, figure_id),
                    content=item.value_text or "",
                    evidence=evidence_text or "",
                    confidence=item.confidence,
                    evidence_type=evidence_type,
                    image_url=image_url,
                    thumbnail_url=image_url,
                    page=asset.page_number if asset is not None else (primary_evidence.page_number if primary_evidence else None),
                    bbox=asset_bbox(metadata),
                    caption=asset.caption if asset is not None else (primary_evidence.source_label if primary_evidence else None),
                    source=figure_id,
                    figure_id=figure_id,
                    notes=item.verification_notes,
                    structured_data=structured_data,
                    parse_status="verified" if item.verified else None,
                    extraction_mode=item.extraction_method,
                    created_at=item.created_at,
                )
            )

        return ExtractionJobRead(
            id=bundle.job.id,
            paper_id=bundle.job.paper_id,
            query=bundle.job.query,
            status=bundle.run.status or bundle.job.status,
            error_message=bundle.run.error_message or bundle.job.error_message,
            created_at=bundle.job.created_at,
            updated_at=bundle.run.updated_at,
            results=results,
            progress=self._progress_for_job(bundle.job),
        )

    def _legacy_structured(self, bundle: ExtractionJobBundle) -> StructuredExtractionResponse:
        from app.services.extraction.legacy_presenter import build_legacy_structured_extraction

        return build_legacy_structured_extraction(self.db, bundle.job, bundle.paper)

    def _run_structured(self, bundle: ExtractionJobBundle) -> StructuredExtractionResponse:
        assert bundle.run is not None
        items = (
            self.db.query(ExtractionItem)
            .filter(ExtractionItem.run_id == bundle.run.id)
            .order_by(ExtractionItem.id.asc())
            .all()
        )
        evidence_rows = (
            self.db.query(ExtractionEvidence)
            .filter(ExtractionEvidence.item_id.in_([item.id for item in items]))
            .order_by(ExtractionEvidence.id.asc())
            .all()
            if items
            else []
        )
        evidence_by_item: dict[int, list[ExtractionEvidence]] = {}
        asset_ids: set[int] = set()
        for evidence in evidence_rows:
            evidence_by_item.setdefault(evidence.item_id, []).append(evidence)
            if evidence.source_id and evidence.source_type in {"figure", "table"}:
                asset_ids.add(evidence.source_id)
        assets_by_id: dict[int, DocumentAsset] = {}
        if asset_ids:
            assets = self.db.query(DocumentAsset).filter(DocumentAsset.id.in_(sorted(asset_ids))).all()
            assets_by_id = {asset.id: asset for asset in assets}

        figure_assets = (
            self.db.query(DocumentAsset)
            .filter(DocumentAsset.document_id == bundle.job.paper_id, DocumentAsset.asset_type.in_(["figure", "page_snapshot"]))
            .all()
        )
        figure_assets = display_visual_assets(figure_assets)
        all_figure_assets = {asset.id: asset for asset in figure_assets if asset.file_path}

        figure_results: list[StructuredFigureResult] = []
        table_results: list[StructuredTableResult] = []
        text_results: list[StructuredTextResult] = []
        not_found: list[str] = []

        for item in items:
            evidences = evidence_by_item.get(item.id, [])
            primary_evidence = evidences[0] if evidences else None
            asset = assets_by_id.get(primary_evidence.source_id) if primary_evidence and primary_evidence.source_id else None
            metadata = asset_metadata(asset)
            evidence_type = normalize_evidence_type(source_type=item.source_type, asset=asset, metadata=metadata)
            if not item.value_text and not item.data_points_json:
                not_found.append(item.indicator)
                continue
            evidence_text = primary_evidence.excerpt if primary_evidence and primary_evidence.excerpt else (primary_evidence.excerpt_context if primary_evidence else "")
            metric = display_field_name(item.indicator, item.source_type, item.figure_label)

            if evidence_type in {"figure", "chart", "page_region"} and (asset and asset.file_path):
                data_points: list[dict] = []
                if item.data_points_json:
                    try:
                        parsed_points = json.loads(item.data_points_json)
                        if isinstance(parsed_points, list):
                            data_points = [point for point in parsed_points if isinstance(point, dict)]
                    except Exception:
                        data_points = []
                text_evidence_refs = [e.excerpt for e in evidences if e.source_type == "text_chunk" and e.excerpt]
                figure_results.append(
                    StructuredFigureResult(
                        id=item.id,
                        figure_id=item.figure_label or (primary_evidence.source_label if primary_evidence else f"Asset {asset.id}"),
                        caption=asset.caption or (primary_evidence.source_label if primary_evidence else ""),
                        image_url=asset_image_url(asset),
                        page=asset.page_number,
                        evidence_type=evidence_type,
                        source=str(metadata.get("source") or asset.asset_type),
                        metric=metric,
                        value=item.value_text or "",
                        evidence=evidence_text,
                        confidence=confidence_label(item.confidence),
                        notes=item.verification_notes,
                        image_type=str(metadata.get("image_type") or metadata.get("sub_type") or metadata.get("visual_role") or ""),
                        review_status="verified" if item.verified else (item.verification_notes or "review_required"),
                        extraction_method=item.extraction_method,
                        data_points=data_points,
                        text_evidence_refs=text_evidence_refs,
                        x_axis_label=item.x_axis_label,
                        x_axis_unit=item.x_axis_unit,
                        x_axis_scale=item.x_axis_scale,
                        y_axis_label=item.y_axis_label,
                        y_axis_unit=item.y_axis_unit,
                        y_axis_scale=item.y_axis_scale,
                        series_name=item.series_name
                    )
                )
            elif evidence_type == "table":
                table_results.append(
                    StructuredTableResult(
                        id=item.id,
                        table_id=primary_evidence.source_label if primary_evidence else None,
                        structured_data=json.dumps(item.data_points_json, ensure_ascii=False) if item.data_points_json else None,
                        parse_status="verified" if item.verified else "partial",
                        page=asset.page_number if asset is not None else (primary_evidence.page_number if primary_evidence else None),
                        evidence_type=evidence_type,
                        source=str(metadata.get("source") or asset.asset_type) if asset is not None else item.source_type,
                        metric=metric,
                        value=item.value_text or "",
                        evidence=evidence_text,
                        notes=item.verification_notes,
                    )
                )
            else:
                text_results.append(
                    StructuredTextResult(
                        id=item.id,
                        metric=metric,
                        value=item.value_text or "",
                        evidence=evidence_text,
                        page=primary_evidence.page_number if primary_evidence else None,
                        evidence_type=evidence_type,
                        source=item.source_type,
                        confidence=confidence_label(item.confidence),
                    )
                )

        paper_figures: list[PaperFigureAsset] = []
        for figure_asset in all_figure_assets.values():
            figure_metadata = asset_metadata(figure_asset)
            figure_source = str(figure_metadata.get("source") or "")
            if figure_source == "fallback_snapshot":
                continue
            evidence_type = normalize_evidence_type(asset=figure_asset, metadata=figure_metadata)
            paper_figures.append(
                PaperFigureAsset(
                    id=figure_asset.id,
                    figure_label=str(figure_metadata.get("figure_label") or figure_asset.label or f"Asset {figure_asset.id}"),
                    caption=str(figure_metadata.get("caption") or figure_asset.caption or ""),
                    image_url=asset_image_url(figure_asset),
                    page=figure_asset.page_number,
                    source=figure_source or figure_asset.asset_type,
                    evidence_type=evidence_type,
                    asset_type=figure_asset.asset_type,
                    coordinate_capable=is_coordinate_asset(figure_asset, figure_metadata),
                    coordinate_preview=coordinate_preview_read(figure_asset, figure_metadata),
                )
            )
        paper_figures.sort(key=lambda row: (row.page or 999, row.id))
        figure_results.extend(
            self._build_figure_backfill_results(
                assets=list(all_figure_assets.values()),
                existing_image_urls={row.image_url for row in figure_results if row.image_url},
            )
        )

        summary = {
            "figures_analyzed": len(figure_results),
            "tables_analyzed": len(table_results),
            "text_items_extracted": len(text_results),
            "failed_items": len(not_found),
            "total_results": len(items),
            "paper_figure_count": len([asset for asset in all_figure_assets.values() if asset.asset_type == "figure"]),
        }
        from app.services.extraction.legacy_presenter import chart_type_stats

        return StructuredExtractionResponse(
            paper_id=bundle.job.paper_id,
            title=bundle.paper.title,
            task=bundle.job.query,
            status=bundle.run.status or bundle.job.status,
            error_message=bundle.run.error_message or bundle.job.error_message,
            summary=summary,
            figure_results=figure_results,
            table_results=table_results,
            text_results=text_results,
            not_found=not_found,
            paper_figures=paper_figures,
            chart_type_stats=chart_type_stats(list(all_figure_assets.values())),
            created_at=bundle.job.created_at,
            updated_at=bundle.run.updated_at,
        )

    def _build_figure_backfill_results(
        self,
        *,
        assets: list[DocumentAsset],
        existing_image_urls: set[str],
    ) -> list[StructuredFigureResult]:
        storage = FileStorageService()
        results: list[StructuredFigureResult] = []
        for asset in assets:
            image_url = asset_image_url(asset)
            if not image_url or image_url in existing_image_urls:
                continue
            metadata = asset_metadata(asset)
            preview = coordinate_preview_read(asset, metadata)
            figure_label = str(metadata.get("figure_label") or asset.label or f"Asset {asset.id}")
            caption = str(metadata.get("caption") or asset.caption or "")
            image_type = str(
                (preview.image_type if preview else "")
                or metadata.get("chart_type")
                or metadata.get("figure_type")
                or metadata.get("visual_role")
                or ""
            )

            csv_data = self._read_full_coordinate_csv(storage, metadata)
            if preview and csv_data and csv_data["data_points"]:
                results.append(
                    StructuredFigureResult(
                        id=-(asset.id * 1000 + 1),
                        figure_id=figure_label,
                        caption=caption,
                        image_url=image_url,
                        page=asset.page_number,
                        evidence_type=normalize_evidence_type(asset=asset, metadata=metadata),
                        source=str(metadata.get("source") or asset.asset_type),
                        metric=csv_data["y_label"] or "value",
                        value=f"CSV: {len(csv_data['data_points'])} 数据点 · {csv_data['x_label']} vs {csv_data['y_label']}",
                        evidence=f"来自坐标预览 CSV，共 {preview.row_count} 个数据点",
                        confidence="high",
                        notes="coordinate_preview_backfill",
                        image_type=image_type,
                        review_status=preview.status or "accepted",
                        extraction_method="coordinate_preview_backfill",
                        data_points=csv_data["data_points"],
                        text_evidence_refs=[],
                        x_axis_label=csv_data["x_label"],
                        x_axis_unit=csv_data["x_unit"],
                        y_axis_label=csv_data["y_label"],
                        y_axis_unit=csv_data["y_unit"],
                        series_name=csv_data.get("series_name", ""),
                    )
                )
                continue

            # 没有坐标 CSV — 不过该图可能已有内容提取结果（text/table），
            # 此处不再创建冗余的"无数据"条目，避免前端展示混淆。
            # 只有当 content extraction 未处理该图且存在坐标预览数据时才 backfill。
            continue
        return results

    def _read_full_coordinate_csv(
        self,
        storage: FileStorageService,
        metadata: dict,
    ) -> dict | None:
        preview = metadata.get("coordinate_preview")
        if not isinstance(preview, dict):
            return None
        csv_path = str(preview.get("coordinate_csv_path") or metadata.get("chart_data_csv_path") or "")
        if not csv_path:
            return None
        try:
            path = storage.get_file_path(csv_path)
        except Exception:
            return None
        if not path.exists():
            return None
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                headers = list(reader.fieldnames or [])
                all_rows = [row for row in reader if isinstance(row, dict)]
        except Exception:
            return None

        # CSV 列名是动态语义的（如 "Shear rate"、"Viscosity (mPa·s)"），
        # 排除已知元数据列，剩余的即是 x/y 数据列。
        META_COLUMNS = {
            "indicator", "series_name", "x_unit", "y_unit",
            "x_scale", "y_scale", "confidence", "quality_tags",
            "panel_id", "curve_role",
        }
        data_cols = [h for h in headers if h not in META_COLUMNS]
        x_col = data_cols[0] if len(data_cols) >= 1 else (headers[0] if headers else "")
        y_col = data_cols[1] if len(data_cols) >= 2 else (x_col if data_cols else (headers[1] if len(headers) >= 2 else ""))

        # x/y column name itself IS the axis label (e.g. "Shear rate (s⁻¹)").
        x_label = x_col
        y_label = y_col

        # Extract unit from column name if in parentheses: "Shear rate (s⁻¹)" → "s⁻¹"
        def _unit_from_col(col: str) -> str:
            if "(" in col and col.endswith(")"):
                return col.split("(")[-1].rstrip(")").strip()
            return ""

        x_unit = _unit_from_col(x_col)
        y_unit = _unit_from_col(y_col)

        series_name = ""
        data_points: list[dict] = []
        for row in all_rows:
            try:
                x_val = float(row.get(x_col) or 0)
                y_val = float(row.get(y_col) or 0)
            except (ValueError, TypeError):
                continue
            point: dict = {
                "x_value": x_val,
                "y_value": y_val,
            }
            # Per-row unit override from x_unit / y_unit columns
            row_x_unit = str(row.get("x_unit") or "").strip()
            row_y_unit = str(row.get("y_unit") or "").strip()
            if row_x_unit:
                point["x_unit"] = row_x_unit
            elif x_unit:
                point["x_unit"] = x_unit
            if row_y_unit:
                point["y_unit"] = row_y_unit
            elif y_unit:
                point["y_unit"] = y_unit

            series = str(row.get("series_name") or "").strip()
            if series:
                point["series_name"] = series
                series_name = series
            error_bar = str(row.get("error_bar") or "").strip()
            if error_bar:
                point["error_bar"] = error_bar
            data_points.append(point)

        return {
            "data_points": data_points,
            "x_label": x_label,
            "x_unit": x_unit,
            "y_label": y_label,
            "y_unit": y_unit,
            "series_name": series_name,
            "row_count": len(all_rows),
        }
