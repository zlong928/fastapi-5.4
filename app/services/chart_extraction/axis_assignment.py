from __future__ import annotations

import numpy as np

from app.services.chart_extraction.axis_calibration import (
    apply_transform,
    axis_calibration_from_ocr,
    infer_axis_labels_from_ocr,
)
from app.services.chart_extraction.chart_recipes import ChartExtractionRecipe, axis_label_recipe, known_axis_recipe
from app.services.chart_extraction.models import ImageRecord


def assign_axis_values(
    record: ImageRecord,
    points: list[dict],
    image: np.ndarray,
    area: tuple[int, int, int, int],
) -> None:
    known = _assign_known_axis_values(record, points)
    if known:
        return
    _assign_ocr_axis_values(record, points, image, area)


def _assign_known_axis_values(record: ImageRecord, points: list[dict]) -> bool:
    recipe = known_axis_recipe(record)
    if recipe:
        _assign_recipe_axis_values(recipe, points)
        return True
    return False


def _assign_recipe_axis_values(recipe: ChartExtractionRecipe, points: list[dict]) -> None:
    for point in points:
        panel = recipe.panel_for_y(float(point["pixel_y"]))
        x_value = recipe.calibrated_x(float(point["pixel_x"]))
        y_value = recipe.calibrated_y(float(point["pixel_y"]))
        point["recipe_id"] = recipe.recipe_id
        point["template_profile_id"] = recipe.template_profile_id
        point["template_binding_policy"] = recipe.template_binding_policy
        point["panel_id"] = panel.panel_id
        point["x_axis_label"] = recipe.x_axis_label
        point["x_axis_unit"] = recipe.x_axis_unit
        point["y_axis_label"] = panel.y_axis_label
        point["y_axis_unit"] = panel.y_axis_unit
        point["x_axis_type"] = recipe.x_axis_type if x_value is not None else "normalized"
        point["y_axis_type"] = recipe.y_axis_type if y_value is not None else "normalized"
        point["x_value"] = x_value if x_value is not None else point["x_coordinate"]
        point["y_value"] = y_value if y_value is not None else point["y_coordinate"]
        point["axis_calibration_method"] = recipe.axis_calibration_method or "recipe_axis"


def _assign_ocr_axis_values(
    record: ImageRecord,
    points: list[dict],
    image: np.ndarray,
    area: tuple[int, int, int, int],
) -> None:
    calibration = axis_calibration_from_ocr(image, area)
    axis_labels = infer_axis_labels_from_ocr(image, area)
    for point in points:
        point.setdefault("panel_id", "plot")
        point.setdefault("x_axis_label", "normalized_x")
        point.setdefault("x_axis_unit", "")
        point.setdefault("y_axis_label", "normalized_y")
        point.setdefault("y_axis_unit", "")
        x_value = apply_transform(calibration.get("x"), float(point["pixel_x"]))
        y_value = apply_transform(calibration.get("y_left"), float(point["pixel_y"]))
        y_right_value = apply_transform(calibration.get("y_right"), float(point["pixel_y"]))
        if x_value is not None:
            point["x_axis_type"] = calibration["x"]["scale"]
            point["x_value"] = round(x_value, 5)
        else:
            point["x_axis_type"] = "normalized"
            point["x_value"] = point["x_coordinate"]
        if y_value is not None:
            point["y_axis_type"] = calibration["y_left"]["scale"]
            point["y_value"] = round(y_value, 5)
        else:
            point["y_axis_type"] = "normalized"
            point["y_value"] = point["y_coordinate"]
        if y_right_value is not None:
            point["y_right_value"] = round(y_right_value, 5)
            point["y_right_axis_type"] = calibration["y_right"]["scale"]
        else:
            point["y_right_value"] = ""
            point["y_right_axis_type"] = ""
        point["axis_calibration_method"] = "ocr_ticks" if x_value is not None or y_value is not None else "normalized_fallback"
        _apply_ocr_axis_labels(axis_labels, point)
        _apply_recipe_axis_labels(record, point)


def _apply_ocr_axis_labels(axis_labels: dict, point: dict) -> None:
    x_label = str(axis_labels.get("x_axis_label") or "")
    y_label = str(axis_labels.get("y_axis_label") or "")
    if _is_supported_axis_label(x_label):
        point["x_axis_label"] = x_label
        point["x_axis_unit"] = axis_labels.get("x_axis_unit") or ""
    if _is_supported_axis_label(y_label):
        point["y_axis_label"] = y_label
        point["y_axis_unit"] = axis_labels.get("y_axis_unit") or ""
    if _is_supported_axis_label(x_label) or _is_supported_axis_label(y_label):
        point["axis_label_binding_method"] = "ocr_axis_title"


def _is_supported_axis_label(label: str) -> bool:
    return label in {
        "Bacteria OD600",
        "G' and G''",
        "Phenol",
        "Shear rate",
        "Strain",
        "Time",
        "Viscosity",
    }


def _apply_recipe_axis_labels(record: ImageRecord, point: dict) -> None:
    recipe = axis_label_recipe(record)
    if not recipe:
        return
    panel = recipe.panel_for_y(float(point["pixel_y"]))
    point["recipe_id"] = recipe.recipe_id
    point["template_profile_id"] = recipe.template_profile_id
    point["template_binding_policy"] = recipe.template_binding_policy
    point["panel_id"] = panel.panel_id
    point["x_axis_label"] = recipe.x_axis_label
    point["x_axis_unit"] = recipe.x_axis_unit
    point["y_axis_label"] = panel.y_axis_label
    point["y_axis_unit"] = panel.y_axis_unit
    if recipe.y_right_axis_type and point.get("y_right_value") not in {"", None}:
        point["y_right_axis_type"] = point.get("y_right_axis_type") or recipe.y_right_axis_type
