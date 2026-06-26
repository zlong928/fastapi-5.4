from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawPixel:
    px: float
    py: float
    rgb: tuple[int, int, int] = (0, 0, 0)
    component_id: int = 0
    color_group: str = ""


@dataclass
class RawExtraction:
    pixels: list[RawPixel] = field(default_factory=list)
    tick_values: list[dict] = field(default_factory=list)
    legend_markers: list[dict] = field(default_factory=list)
    detection_method: str = ""
