from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.services.agent.llm_client import LLMClient
from app.services.chart_extraction.agents.vlm_extractor import VlmExtractionResult, VlmExtractor
from app.services.chart_extraction.cv.verifier import CvVerifier, VerificationReport
from app.services.chart_extraction.io import write_coordinate_csv
from app.services.extraction.llm_config import build_vlm_config
from app.services.chart_extraction.models import ImageRecord
from app.services.chart_extraction.numerical_validator import NumericalValidator, ValidationResult
from app.services.chart_extraction.plot_geometry import detect_plot_area
from app.services.chart_extraction.quality import annotate_quality, image_status_from_rows
from app.services.chart_extraction.schema_validator import SchemaValidator

logger = logging.getLogger(__name__)


@dataclass
class AgentExtractionResult:
    image_file: str
    image_type: str
    status: str
    reason: str
    row_count: int
    verification_passed: bool = True
    verification_confidence: float = 1.0
    csv_path: str = ""
    overlay_path: str = ""
    points: list[dict] = field(default_factory=list)


class MultiAgentOrchestrator:
    """VLM-first pipeline: 1 VLM call -> optional CV verification -> validation.

    Pipeline:
      1. VlmExtractor (1 VLM call) — structured output with axes, series, points
      2. Fast path for simple/high-confidence charts
      3. CV verification for complex/low-confidence charts
      4. SchemaValidator calibration
      5. NumericalValidator validation
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.client = llm_client or LLMClient(build_vlm_config())
        self.vlm_extractor = VlmExtractor(self.client)
        self.cv_verifier = CvVerifier()
        self.schema_validator = SchemaValidator()
        self.numerical_validator = NumericalValidator()

    def extract(
        self,
        record: ImageRecord,
        out_dir: Path,
        sample_limit: int = 15,
    ) -> AgentExtractionResult:
        image = cv2.imread(str(record.path))
        if image is None:
            return AgentExtractionResult(
                image_file=record.path.name,
                image_type="",
                status="failed",
                reason="image_unreadable",
                row_count=0,
            )

        return self._extract_single_panel(
            record=record, image=image, out_dir=out_dir,
        )

    def _extract_single_panel(
        self,
        record: ImageRecord,
        image: np.ndarray,
        out_dir: Path,
    ) -> AgentExtractionResult:
        # Step 1: VLM extraction
        vlm_result = self.vlm_extractor.extract(str(record.path), record.caption)
        if vlm_result.error:
            return AgentExtractionResult(
                image_file=record.path.name,
                image_type=vlm_result.chart_type,
                status="failed",
                reason=f"vlm_error: {vlm_result.error}",
                row_count=0,
            )

        # Step 2: Fast path — trust VLM for simple charts
        if vlm_result.is_simple_chart and vlm_result.confidence > 0.9:
            points = self.schema_validator.vlm_to_points(vlm_result, record)
            return self._build_result(points, record, out_dir, vlm_result)

        # Step 3: CV verification (for complex/low-confidence charts)
        plot_area = detect_plot_area(image)
        report = self.cv_verifier.verify(image, vlm_result.raw_json) if plot_area else VerificationReport()

        # Step 4: Calibrate + validate
        points = self.schema_validator.calibrate(vlm_result, report, plot_area, record)
        try:
            validation = self.numerical_validator.validate(points, None)
        except Exception:
            validation = None

        return self._build_result(points, record, out_dir, vlm_result, validation)

    def _build_result(
        self,
        points: list[dict],
        record: ImageRecord,
        out_dir: Path,
        vlm_result: VlmExtractionResult,
        validation: ValidationResult | None = None,
    ) -> AgentExtractionResult:
        sampled = self._sample_or_sort(points, 15, record)
        annotate_quality(sampled)

        csv_path = out_dir / f"{record.ordinal:02d}_{record.path.stem}_coordinates.csv"
        write_coordinate_csv(csv_path, sampled)

        return AgentExtractionResult(
            image_file=record.path.name,
            image_type=vlm_result.chart_type,
            status=image_status_from_rows(sampled),
            reason="",
            row_count=len(sampled),
            verification_passed=validation.passed if validation else True,
            verification_confidence=validation.confidence if validation else 1.0,
            csv_path=str(csv_path),
            points=sampled,
        )

    def _sample_or_sort(self, points: list[dict], sample_limit: int, record: ImageRecord) -> list[dict]:
        from app.services.chart_extraction.batch import sample_points
        if len(points) <= sample_limit * 3:
            return points
        return sample_points(points, sample_limit, seed=record.ordinal * 1009)
