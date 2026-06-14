from __future__ import annotations

import numpy as np

from app.services.chart_extraction.extractors.colorbar import map_rgb_to_colorbar_value


def grid_color_samples(
    image: np.ndarray,
    area: tuple[int, int, int, int],
    rows: int,
    cols: int,
    panel_id: str,
    x_axis_label: str,
    y_axis_label: str,
    axis_type: str,
    calibration_method: str,
    colorbar_mapping: dict | None = None,
) -> list[dict]:
    x0, y0, x1, y1 = area
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    cell_area = max(1, int(width * height / max(1, rows * cols)))
    points: list[dict] = []
    for row in range(rows):
        for col in range(cols):
            px = x0 + (col + 0.5) * width / cols
            py = y0 + (row + 0.5) * height / rows
            bgr = image[int(round(py)), int(round(px))].astype(float)
            rgb = np.array([bgr[2], bgr[1], bgr[0]])
            luminance = float(0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255.0
            mapped_value = map_rgb_to_colorbar_value(rgb, colorbar_mapping)
            colorbar_bound = mapped_value is not None
            colorbar_bbox = colorbar_mapping.get("bbox", ("", "", "", "")) if colorbar_mapping else ("", "", "", "")
            points.append(
                {
                    "panel_id": panel_id,
                    "pixel_x": round(float(px), 1),
                    "pixel_y": round(float(py), 1),
                    "x_coordinate": round((px - x0) / width, 5),
                    "y_coordinate": round(1 - (py - y0) / height, 5),
                    "x_value": col,
                    "y_value": row,
                    "x_axis_label": x_axis_label,
                    "x_axis_unit": "",
                    "y_axis_label": y_axis_label,
                    "y_axis_unit": "",
                    "x_axis_type": axis_type,
                    "y_axis_type": axis_type,
                    "z_value": round(mapped_value, 5) if colorbar_bound else round(luminance, 5),
                    "z_axis_label": "colorbar_value" if colorbar_bound else "color_intensity",
                    "z_axis_unit": colorbar_mapping.get("unit", "") if colorbar_bound else "normalized_luminance",
                    "z_axis_type": "colorbar_mapped" if colorbar_bound else "rgb_luminance_normalized",
                    "colorbar_min_value": colorbar_mapping.get("min_value", "") if colorbar_mapping else "",
                    "colorbar_max_value": colorbar_mapping.get("max_value", "") if colorbar_mapping else "",
                    "colorbar_unit": colorbar_mapping.get("unit", "") if colorbar_mapping else "",
                    "colorbar_binding_status": colorbar_mapping.get("binding_status", "") if colorbar_mapping else "",
                    "colorbar_binding_method": colorbar_mapping.get("binding_method", "") if colorbar_mapping else "",
                    "colorbar_tick_count": colorbar_mapping.get("tick_count", "") if colorbar_mapping else "",
                    "colorbar_tick_confidence": colorbar_mapping.get("tick_confidence", "") if colorbar_mapping else "",
                    "colorbar_top_value": colorbar_mapping.get("top_value", "") if colorbar_mapping else "",
                    "colorbar_top_y_px": colorbar_mapping.get("top_y", "") if colorbar_mapping else "",
                    "colorbar_bottom_value": colorbar_mapping.get("bottom_value", "") if colorbar_mapping else "",
                    "colorbar_bottom_y_px": colorbar_mapping.get("bottom_y", "") if colorbar_mapping else "",
                    "colorbar_left_px": colorbar_bbox[0],
                    "colorbar_right_px": colorbar_bbox[2],
                    "colorbar_top_px": colorbar_bbox[1],
                    "colorbar_bottom_px": colorbar_bbox[3],
                    "color_group": f"rgb_{int(rgb[0])}_{int(rgb[1])}_{int(rgb[2])}",
                    "component_area_px": cell_area,
                    "axis_calibration_method": f"{calibration_method}_colorbar" if colorbar_bound else calibration_method,
                }
            )
    return points
