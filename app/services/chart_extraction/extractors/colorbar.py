from __future__ import annotations

import cv2
import numpy as np

from app.services.chart_extraction.axis_calibration import parse_numeric_token

try:
    import pytesseract
except Exception:  # pragma: no cover - optional runtime dependency
    pytesseract = None


def _ocr_numeric_tokens(image: np.ndarray) -> list[dict]:
    if pytesseract is None:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    try:
        data = pytesseract.image_to_data(enlarged, config="--psm 6", output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    tokens: list[dict] = []
    for index, raw_text in enumerate(data.get("text", [])):
        value = parse_numeric_token(str(raw_text))
        if value is None:
            continue
        try:
            confidence = float(data["conf"][index])
        except Exception:
            confidence = -1.0
        if confidence < 20:
            continue
        left = float(data["left"][index]) / 2
        top = float(data["top"][index]) / 2
        width = float(data["width"][index]) / 2
        height = float(data["height"][index]) / 2
        tokens.append(
            {
                "value": value,
                "confidence": confidence,
                "cx": left + width / 2,
                "cy": top + height / 2,
                "left": left,
                "right": left + width,
            }
        )
    return tokens


def _candidate_regions(image: np.ndarray, area: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    height, width = image.shape[:2]
    x0, y0, x1, y1 = area
    regions: list[tuple[int, int, int, int]] = []
    if x1 + 8 < width:
        regions.append((x1 + 4, max(0, y0), width - 1, min(height - 1, y1)))
    regions.append((int(width * 0.65), max(0, y0), width - 1, min(height - 1, y1)))
    return regions


def detect_vertical_colorbar(image: np.ndarray, area: tuple[int, int, int, int]) -> dict | None:
    best: dict | None = None
    for rx0, ry0, rx1, ry1 in _candidate_regions(image, area):
        if rx1 <= rx0 or ry1 <= ry0:
            continue
        crop = image[ry0 : ry1 + 1, rx0 : rx1 + 1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(float)
        col_std = gray.std(axis=0)
        row_range = gray.max(axis=0) - gray.min(axis=0)
        active = (col_std > 12) & (row_range > 35)
        start = None
        for idx, value in enumerate(list(active) + [False]):
            if value and start is None:
                start = idx
            if not value and start is not None:
                end = idx - 1
                width = end - start + 1
                if 3 <= width <= 45:
                    x_left = rx0 + start
                    x_right = rx0 + end
                    strip = image[ry0 : ry1 + 1, x_left : x_right + 1]
                    strip_gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY).astype(float)
                    vertical_span = float(np.percentile(strip_gray, 95) - np.percentile(strip_gray, 5))
                    score = vertical_span * min(width, 12)
                    if vertical_span > 35 and (best is None or score > best["score"]):
                        best = {
                            "bbox": (x_left, ry0, x_right, ry1),
                            "score": score,
                        }
                start = None
    return best


def build_colorbar_mapping(image: np.ndarray, area: tuple[int, int, int, int]) -> dict | None:
    bar = detect_vertical_colorbar(image, area)
    if not bar:
        return None
    bx0, by0, bx1, by1 = bar["bbox"]
    tokens = _ocr_numeric_tokens(image)
    nearby = [
        token
        for token in tokens
        if by0 - 12 <= float(token["cy"]) <= by1 + 12
        and (bx1 + 1 <= float(token["left"]) <= bx1 + 80 or bx0 - 80 <= float(token["right"]) <= bx0 - 1)
    ]
    if len(nearby) < 2:
        return {
            "bbox": bar["bbox"],
            "binding_status": "colorbar_detected_without_ticks",
            "binding_method": "vertical_gradient_detected",
            "tick_count": len(nearby),
        }
    ticks = sorted(nearby, key=lambda token: float(token["cy"]))
    top = ticks[0]
    bottom = ticks[-1]
    if abs(float(top["value"]) - float(bottom["value"])) < 1e-12:
        return {
            "bbox": bar["bbox"],
            "binding_status": "colorbar_detected_without_ticks",
            "binding_method": "vertical_gradient_detected",
            "tick_count": len(nearby),
        }
    strip = image[by0 : by1 + 1, bx0 : bx1 + 1].astype(float)
    profile = strip.mean(axis=1)
    tick_confidence = sum(float(token["confidence"]) for token in ticks) / len(ticks)
    return {
        "bbox": bar["bbox"],
        "top_y": float(top["cy"]),
        "top_value": float(top["value"]),
        "top_confidence": float(top["confidence"]),
        "bottom_y": float(bottom["cy"]),
        "bottom_value": float(bottom["value"]),
        "bottom_confidence": float(bottom["confidence"]),
        "min_value": min(float(top["value"]), float(bottom["value"])),
        "max_value": max(float(top["value"]), float(bottom["value"])),
        "profile_rgb": profile[:, ::-1],
        "binding_status": "colorbar_ticks_bound_review",
        "binding_method": "vertical_gradient_tick_ocr",
        "tick_count": len(ticks),
        "tick_confidence": round(tick_confidence, 1),
    }


def map_rgb_to_colorbar_value(rgb: np.ndarray, mapping: dict | None) -> float | None:
    if not mapping or mapping.get("binding_status") != "colorbar_ticks_bound_review":
        return None
    profile = np.asarray(mapping["profile_rgb"], dtype=float)
    if profile.size == 0:
        return None
    distances = np.linalg.norm(profile - rgb.astype(float), axis=1)
    row = float(np.argmin(distances))
    by0 = float(mapping["bbox"][1])
    by1 = float(mapping["bbox"][3])
    pixel_y = by0 + row
    top_y = float(mapping["top_y"])
    bottom_y = float(mapping["bottom_y"])
    if abs(bottom_y - top_y) < 1e-9:
        return None
    fraction = (pixel_y - top_y) / (bottom_y - top_y)
    value = float(mapping["top_value"]) + fraction * (float(mapping["bottom_value"]) - float(mapping["top_value"]))
    return value
