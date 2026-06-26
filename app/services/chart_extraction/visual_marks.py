from __future__ import annotations

import cv2
import numpy as np


def classify_mark_color(rgb: np.ndarray) -> str:
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    spread = max_c - min_c

    # Black: all channels very low
    if max_c < 60:
        return "black"
    # Gray: channels close to each other (luminance-dominant, not too bright)
    if spread < 40:
        return "gray"
    # Light/washed out
    if min_c > 180 and spread < 60:
        return "gray"

    if r > 170 and g > 100 and b < 130 and r > g * 1.1:
        return "orange"
    if r > 70 and g > 40 and b < 90 and r > g * 1.2 and r > b * 1.8:
        return "brown"
    if r > 145 and g < 120 and b < 140 and r > g * 1.2:
        return "red"

    # Blue / Green: dominant channel with ratio check
    if b > r * 1.15 and b > g * 1.15:
        return "blue"
    if g > r * 1.15 and g > b * 1.15:
        return "green"

    # Edge cases: strong channel wins
    if b >= r and b >= g:
        return "blue"
    if g >= r and g >= b:
        return "green"
    return "red"


def data_mask(image: np.ndarray, area: tuple[int, int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, x1, y1 = area
    crop = image[y0 : y1 + 1, x0 : x1 + 1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    saturated = (hsv[:, :, 1] > 30) & (hsv[:, :, 2] > 35)
    medium_gray = (gray > 60) & (gray < 205) & (hsv[:, :, 1] < 45)
    mask = (saturated | medium_gray).astype("uint8") * 255
    mask[gray < 35] = 0
    return crop, cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def component_points(image: np.ndarray, area: tuple[int, int, int, int]) -> list[dict]:
    x0, y0, x1, y1 = area
    crop, mask = data_mask(image, area)
    h, w = mask.shape
    mask[int(h * 0.58) :, : int(w * 0.36)] = 0
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    points: list[dict] = []
    for label in range(1, num):
        area_px = int(stats[label, cv2.CC_STAT_AREA])
        if not (8 <= area_px <= max(900, int(w * h * 0.025))):
            continue
        cx, cy = centroids[label]
        px = float(cx + x0)
        py = float(cy + y0)
        if not (x0 <= px <= x1 and y0 <= py <= y1):
            continue
        margin_x = max(4, (x1 - x0) * 0.025)
        margin_y = max(4, (y1 - y0) * 0.025)
        if px <= x0 + margin_x or px >= x1 - margin_x or py <= y0 + margin_y or py >= y1 - margin_y:
            continue
        comp = labels == label
        pix_bgr = crop[comp]
        pix_hsv = cv2.cvtColor(pix_bgr.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
        score = pix_hsv[:, 1].astype(float) + (255 - pix_hsv[:, 2].astype(float)) * 0.25
        keep = max(3, int(len(score) * 0.4))
        idx = np.argsort(score)[-keep:]
        mean_bgr = pix_bgr[idx].mean(axis=0)
        rgb = np.array([mean_bgr[2], mean_bgr[1], mean_bgr[0]])
        color = classify_mark_color(rgb)
        points.append(
            {
                "pixel_x": round(px, 1),
                "pixel_y": round(py, 1),
                "x_coordinate": round((px - x0) / max(1, x1 - x0), 5),
                "y_coordinate": round(1 - (py - y0) / max(1, y1 - y0), 5),
                "color_group": color,
                "component_area_px": area_px,
            }
        )
    return points


def colored_curve_points(image: np.ndarray, area: tuple[int, int, int, int]) -> list[dict]:
    x0, y0, x1, y1 = area
    crop = image[y0 : y1 + 1, x0 : x1 + 1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    mask = ((hsv[:, :, 1] > 55) & (hsv[:, :, 2] > 45)).astype("uint8") * 255
    mask[: int(h * 0.28), int(w * 0.55) :] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    num, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    points: list[dict] = []
    for label in range(1, num):
        area_px = int(stats[label, cv2.CC_STAT_AREA])
        if not (6 <= area_px <= max(1800, int(w * h * 0.08))):
            continue
        comp = labels == label
        ys, xs = np.where(comp)
        if len(xs) == 0:
            continue
        pix_bgr = crop[comp]
        mean_bgr = pix_bgr.mean(axis=0)
        color = classify_mark_color(np.array([mean_bgr[2], mean_bgr[1], mean_bgr[0]]))
        x_span = int(xs.max() - xs.min())
        if len(xs) > 40 and x_span >= max(8, int(w * 0.04)):
            bin_count = min(8, max(3, int(x_span / max(1, w) * 10)))
            bins = np.linspace(xs.min(), xs.max() + 1, bin_count + 1)
            for left, right in zip(bins[:-1], bins[1:]):
                keep = (xs >= left) & (xs < right)
                if keep.sum() < 3:
                    continue
                px = float(np.median(xs[keep]) + x0)
                py = float(np.median(ys[keep]) + y0)
                points.append(
                    {
                        "pixel_x": round(px, 1),
                        "pixel_y": round(py, 1),
                        "x_coordinate": round((px - x0) / max(1, x1 - x0), 5),
                        "y_coordinate": round(1 - (py - y0) / max(1, y1 - y0), 5),
                        "color_group": color,
                        "component_area_px": area_px,
                    }
                )
        else:
            px = float(np.median(xs) + x0)
            py = float(np.median(ys) + y0)
            points.append(
                {
                    "pixel_x": round(px, 1),
                    "pixel_y": round(py, 1),
                    "x_coordinate": round((px - x0) / max(1, x1 - x0), 5),
                    "y_coordinate": round(1 - (py - y0) / max(1, y1 - y0), 5),
                    "color_group": color,
                    "component_area_px": area_px,
                }
            )
    return points


def merge_marker_components(points: list[dict], marker_points: list[dict]) -> list[dict]:
    merged = list(points)
    for marker in marker_points:
        if marker.get("color_group") == "gray" or int(marker.get("component_area_px") or 0) < 35:
            continue
        px = float(marker["pixel_x"])
        py = float(marker["pixel_y"])
        if any(abs(float(existing["pixel_x"]) - px) < 6 and abs(float(existing["pixel_y"]) - py) < 6 for existing in merged):
            continue
        merged.append(marker)
    return merged
