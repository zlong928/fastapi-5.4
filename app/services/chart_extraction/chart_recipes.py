from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.services.chart_extraction.models import ImageRecord


@dataclass(frozen=True)
class PanelRecipe:
    panel_id: str
    y_top_px: float
    y_bottom_px: float
    y_axis_label: str
    y_axis_unit: str

    def contains(self, pixel_y: float) -> bool:
        return self.y_top_px <= pixel_y <= self.y_bottom_px

    def normalized_y(self, pixel_y: float) -> float:
        return round(1 - (pixel_y - self.y_top_px) / max(1, self.y_bottom_px - self.y_top_px), 5)


@dataclass(frozen=True)
class ChartExtractionRecipe:
    recipe_id: str
    image_type: str
    filename_prefixes: tuple[str, ...]
    caption_hints: tuple[str, ...]
    x_axis_label: str
    x_axis_unit: str
    panels: tuple[PanelRecipe, ...]
    x_axis_type: str = "linear"
    y_axis_type: str = "linear"
    axis_calibration_method: str = ""
    x_log_a: float | None = None
    x_log_b: float | None = None
    y_log_a: float | None = None
    y_log_b: float | None = None
    y_right_axis_type: str = ""
    template_profile_id: str = ""
    template_binding_policy: str = "axis_only"
    source_path: str = ""

    def matches(self, record: ImageRecord) -> bool:
        filename = Path(record.path).name
        caption = record.caption.lower()
        return filename.startswith(self.filename_prefixes) or any(hint in caption for hint in self.caption_hints)

    def panel_for_y(self, pixel_y: float) -> PanelRecipe:
        for panel in self.panels:
            if panel.contains(pixel_y):
                return panel
        return self.panels[-1] if pixel_y > self.panels[-1].y_bottom_px else self.panels[0]

    def calibrated_y(self, pixel_y: float) -> float | None:
        if self.y_log_a is None or self.y_log_b is None:
            return None
        return round(10 ** (self.y_log_a * pixel_y + self.y_log_b), 5)

    def calibrated_x(self, pixel_x: float) -> float | None:
        if self.x_log_a is None or self.x_log_b is None:
            return None
        return round(10 ** (self.x_log_a * pixel_x + self.x_log_b), 5)


RECIPES_DIR = Path(__file__).resolve().parent / "recipes"
BIPHASIC_RECIPE_PATH = RECIPES_DIR / "biphasic_time_series.json"
SPECTRUM_RECIPE_PATH = RECIPES_DIR / "spectrum_curve.json"
LINE_PLOT_RECIPE_PATH = RECIPES_DIR / "line_plot.json"
BIPHASIC_TIME_SERIES_RECIPES: tuple[ChartExtractionRecipe, ...] = tuple()
SPECTRUM_CURVE_RECIPES: tuple[ChartExtractionRecipe, ...] = tuple()
LINE_PLOT_RECIPES: tuple[ChartExtractionRecipe, ...] = tuple()
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_recipe_file(path: Path) -> tuple[ChartExtractionRecipe, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Recipe file must contain a list: {path}")
    return tuple(_recipe_from_dict(item, path) for item in payload)


def _recipe_from_dict(item: dict, path: Path) -> ChartExtractionRecipe:
    panels = item.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError(f"Recipe {item.get('recipe_id')} must define at least one panel")
    return ChartExtractionRecipe(
        recipe_id=str(item["recipe_id"]),
        image_type=str(item["image_type"]),
        filename_prefixes=tuple(str(value) for value in item.get("filename_prefixes", [])),
        caption_hints=tuple(str(value).lower() for value in item.get("caption_hints", [])),
        x_axis_label=str(item["x_axis_label"]),
        x_axis_unit=str(item.get("x_axis_unit") or ""),
        panels=tuple(
            PanelRecipe(
                panel_id=str(panel["panel_id"]),
                y_top_px=float(panel["y_top_px"]),
                y_bottom_px=float(panel["y_bottom_px"]),
                y_axis_label=str(panel["y_axis_label"]),
                y_axis_unit=str(panel.get("y_axis_unit") or ""),
            )
            for panel in panels
        ),
        x_axis_type=str(item.get("x_axis_type") or "linear"),
        y_axis_type=str(item.get("y_axis_type") or "linear"),
        axis_calibration_method=str(item.get("axis_calibration_method") or ""),
        x_log_a=float(item["x_log_a"]) if item.get("x_log_a") is not None else None,
        x_log_b=float(item["x_log_b"]) if item.get("x_log_b") is not None else None,
        y_log_a=float(item["y_log_a"]) if item.get("y_log_a") is not None else None,
        y_log_b=float(item["y_log_b"]) if item.get("y_log_b") is not None else None,
        y_right_axis_type=str(item.get("y_right_axis_type") or ""),
        template_profile_id=str(item.get("template_profile_id") or ""),
        template_binding_policy=str(item.get("template_binding_policy") or "axis_only"),
        source_path=_portable_source_path(path),
    )


def _portable_source_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


BIPHASIC_TIME_SERIES_RECIPES = _load_recipe_file(BIPHASIC_RECIPE_PATH)
SPECTRUM_CURVE_RECIPES = _load_recipe_file(SPECTRUM_RECIPE_PATH)
LINE_PLOT_RECIPES = _load_recipe_file(LINE_PLOT_RECIPE_PATH)


def biphasic_time_series_recipe(record: ImageRecord) -> ChartExtractionRecipe | None:
    for recipe in BIPHASIC_TIME_SERIES_RECIPES:
        if recipe.matches(record):
            return recipe
    return None


def spectrum_curve_recipe(record: ImageRecord) -> ChartExtractionRecipe | None:
    for recipe in SPECTRUM_CURVE_RECIPES:
        if recipe.matches(record):
            return recipe
    return None


def line_plot_recipe(record: ImageRecord) -> ChartExtractionRecipe | None:
    for recipe in LINE_PLOT_RECIPES:
        if recipe.matches(record):
            return recipe
    return None


def axis_label_recipe(record: ImageRecord) -> ChartExtractionRecipe | None:
    for recipe in all_chart_recipes():
        if recipe.matches(record):
            return recipe
    return None


def known_axis_recipe(record: ImageRecord) -> ChartExtractionRecipe | None:
    for recipe in SPECTRUM_CURVE_RECIPES + LINE_PLOT_RECIPES:
        if recipe.axis_calibration_method and recipe.matches(record):
            return recipe
    return None


def all_chart_recipes() -> tuple[ChartExtractionRecipe, ...]:
    return BIPHASIC_TIME_SERIES_RECIPES + SPECTRUM_CURVE_RECIPES + LINE_PLOT_RECIPES


def chart_recipe_catalog() -> list[dict]:
    return [
        {
            "recipe_id": recipe.recipe_id,
            "image_type": recipe.image_type,
            "filename_prefixes": list(recipe.filename_prefixes),
            "caption_hints": list(recipe.caption_hints),
            "x_axis_label": recipe.x_axis_label,
            "x_axis_unit": recipe.x_axis_unit,
            "x_axis_type": recipe.x_axis_type,
            "y_axis_type": recipe.y_axis_type,
            "axis_calibration_method": recipe.axis_calibration_method,
            "template_profile_id": recipe.template_profile_id,
            "template_binding_policy": recipe.template_binding_policy,
            "known_x_axis_calibrated": recipe.x_log_a is not None and recipe.x_log_b is not None,
            "known_y_axis_calibrated": recipe.y_log_a is not None and recipe.y_log_b is not None,
            "y_right_axis_type": recipe.y_right_axis_type,
            "source_path": recipe.source_path,
            "panels": [
                {
                    "panel_id": panel.panel_id,
                    "y_top_px": panel.y_top_px,
                    "y_bottom_px": panel.y_bottom_px,
                    "y_axis_label": panel.y_axis_label,
                    "y_axis_unit": panel.y_axis_unit,
                }
                for panel in recipe.panels
            ],
        }
        for recipe in all_chart_recipes()
    ]
