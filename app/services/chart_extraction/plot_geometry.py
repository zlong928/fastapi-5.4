from __future__ import annotations

import cv2
import numpy as np

from app.services.chart_extraction.axis_calibration import ocr_text_tokens


def detect_plot_area(image: np.ndarray) -> tuple[int, int, int, int]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = gray < 90
    h, w = gray.shape
    frame_dark = gray < 80
    col_counts = frame_dark.sum(axis=0)
    row_counts = frame_dark.sum(axis=1)
    verticals = np.where(col_counts > h * 0.35)[0]
    horizontals = np.where(row_counts > w * 0.35)[0]
    if len(verticals) >= 2:
        x0 = int(verticals.min())
        x1 = int(verticals.max())
        y_candidates = np.where(frame_dark[:, x0 : x1 + 1].sum(axis=1) > max(8, (x1 - x0) * 0.08))[0]
        if len(horizontals) >= 2:
            y0 = int(horizontals.min())
            y1 = int(horizontals.max())
        elif len(horizontals) == 1 and len(y_candidates):
            y1 = int(horizontals.max())
            y0 = int(max(0, np.percentile(y_candidates, 2)))
        else:
            y0 = int(max(0, np.percentile(y_candidates, 2))) if len(y_candidates) else 0
            y1 = int(min(h - 1, np.percentile(y_candidates, 98))) if len(y_candidates) else h - 1
        if x1 - x0 > w * 0.45 and y1 - y0 > h * 0.35:
            return (x0, y0, x1, y1)
    if len(verticals) == 1 and len(horizontals) >= 2:
        x0 = int(verticals[0])
        y0 = int(horizontals.min())
        y1 = int(horizontals.max())
        band = frame_dark[max(0, y1 - 1) : min(h, y1 + 2), :]
        xs = np.where(band.sum(axis=0) > 0)[0]
        if len(xs):
            x1 = int(xs.max())
            if x1 - x0 > w * 0.45 and y1 - y0 > h * 0.35:
                return (x0, y0, x1, y1)

    ys, xs = np.where(dark)
    if len(xs) == 0:
        return (0, 0, w - 1, h - 1)
    x0, x1 = np.percentile(xs, [2, 98]).astype(int)
    y0, y1 = np.percentile(ys, [2, 98]).astype(int)
    pad_x = max(4, int(w * 0.01))
    pad_y = max(4, int(h * 0.01))
    return (max(0, x0 - pad_x), max(0, y0 - pad_y), min(w - 1, x1 + pad_x), min(h - 1, y1 + pad_y))


def detect_stacked_plot_panels(
    image: np.ndarray,
    area: tuple[int, int, int, int],
) -> list[tuple[str, tuple[int, int, int, int]]]:
    x0, y0, x1, y1 = area
    if y1 <= y0 or x1 <= x0:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    crop = gray[y0 : y1 + 1, x0 : x1 + 1]
    dark = crop < 95
    height, width = dark.shape
    row_counts = dark.sum(axis=1)
    strong_rows = np.where(row_counts > width * 0.45)[0]
    if len(strong_rows) < 3:
        return _detect_stacked_panels_from_y_axis_titles(image, area)

    groups: list[tuple[int, int]] = []
    start = int(strong_rows[0])
    previous = int(strong_rows[0])
    for row in strong_rows[1:]:
        row = int(row)
        if row - previous > 2:
            groups.append((start, previous))
            start = row
        previous = row
    groups.append((start, previous))

    candidates = [
        int((top + bottom) / 2)
        for top, bottom in groups
        if height * 0.25 < (top + bottom) / 2 < height * 0.75
    ]
    if not candidates:
        return _detect_stacked_panels_from_y_axis_titles(image, area)
    split = min(candidates, key=lambda row: abs(row - height / 2))
    upper = (x0, y0, x1, y0 + max(0, split - 1))
    lower = (x0, y0 + min(height - 1, split + 1), x1, y1)
    if upper[3] - upper[1] < height * 0.22 or lower[3] - lower[1] < height * 0.22:
        return _detect_stacked_panels_from_y_axis_titles(image, area)
    return [("upper_panel", upper), ("lower_panel", lower)]


def _detect_stacked_panels_from_y_axis_titles(
    image: np.ndarray,
    area: tuple[int, int, int, int],
) -> list[tuple[str, tuple[int, int, int, int]]]:
    x0, y0, x1, y1 = area
    height, width = image.shape[:2]
    region_top = max(0, y0 - 8)
    region_bottom = min(height, y1 + 8)
    region_left = max(0, x0 - 120)
    region_right = min(width, x0 + 30)
    if region_bottom <= region_top or region_right <= region_left:
        return []
    region = image[region_top:region_bottom, region_left:region_right]
    rotated = cv2.rotate(region, cv2.ROTATE_90_CLOCKWISE)
    region_height = region.shape[0]
    label_positions: dict[str, list[float]] = {"upper": [], "lower": []}
    for token in ocr_text_tokens(rotated, min_confidence=45):
        text = str(token.get("text") or "").lower()
        original_y = region_top + (region_height - float(token.get("cx") or 0))
        if "viscosity" in text:
            label_positions["lower"].append(original_y)
        if text.startswith("g") or "pa" in text:
            label_positions["upper"].append(original_y)
    if not label_positions["upper"] or not label_positions["lower"]:
        return []
    upper_center = float(np.mean(label_positions["upper"]))
    lower_center = float(np.mean(label_positions["lower"]))
    if lower_center <= upper_center or lower_center - upper_center < (y1 - y0) * 0.18:
        return []
    split = int(round((upper_center + lower_center) / 2))
    upper = (x0, y0, x1, max(y0, split - 1))
    lower = (x0, min(y1, split + 1), x1, y1)
    if upper[3] - upper[1] < (y1 - y0) * 0.22 or lower[3] - lower[1] < (y1 - y0) * 0.22:
        return []
    return [("upper_panel", upper), ("lower_panel", lower)]
