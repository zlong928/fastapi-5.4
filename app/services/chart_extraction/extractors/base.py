from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.services.chart_extraction.models import ImageRecord


@dataclass
class ExtractorContext:
    record: ImageRecord
    image: np.ndarray
    plot_area: tuple[int, int, int, int]


@dataclass
class ExtractorResult:
    image_type: str
    points: list[dict]
    extraction_method: str = "local_cv_review_sample"


class ImageExtractor(Protocol):
    image_type: str

    def extract(self, context: ExtractorContext) -> ExtractorResult:
        ...
