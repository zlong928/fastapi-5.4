from __future__ import annotations

import cv2
import numpy as np

try:
    import pytesseract
except Exception:  # pragma: no cover - optional runtime dependency
    pytesseract = None


SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹°", "01234567890")
TEXT_TRANSLATION = str.maketrans({"’": "'", "‘": "'", "′": "'", "″": '"', "·": "*", "−": "-"})


def parse_numeric_token(text: str) -> float | None:
    raw = text.strip()
    if not any(ch.isdigit() or ch in "⁰¹²³⁴⁵⁶⁷⁸⁹°" for ch in raw):
        return None
    cleaned = raw.replace(",", "").replace("−", "-").translate(SUPERSCRIPT_DIGITS)
    cleaned = cleaned.replace("O", "0").replace("o", "0")
    if not cleaned:
        return None
    if raw.startswith("10") and len(raw) >= 3 and raw[2] in "⁰¹²³⁴⁵⁶⁷⁸⁹°":
        try:
            return float(10 ** int(raw[2].translate(SUPERSCRIPT_DIGITS)))
        except ValueError:
            return None
    if cleaned.startswith("10^"):
        try:
            return float(10 ** float(cleaned[3:]))
        except ValueError:
            return None
    allowed = "".join(ch for ch in cleaned if ch.isdigit() or ch in ".-")
    if "." not in raw and allowed.isdigit() and len(allowed) == 2 and allowed.startswith("0") and allowed != "00":
        return float(f"0.{allowed[1]}")
    if allowed in {"", ".", "-", "-."}:
        return None
    try:
        return float(allowed)
    except ValueError:
        return None


def ocr_numeric_tokens(image: np.ndarray) -> list[dict]:
    if pytesseract is None:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = 2
    enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    try:
        data = pytesseract.image_to_data(enlarged, config="--psm 6", output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    tokens: list[dict] = []
    for index, text in enumerate(data.get("text", [])):
        value = parse_numeric_token(str(text))
        if value is None:
            continue
        try:
            confidence = float(data["conf"][index])
        except Exception:
            confidence = -1.0
        if confidence < 20:
            continue
        left = float(data["left"][index]) / scale
        top = float(data["top"][index]) / scale
        width = float(data["width"][index]) / scale
        height = float(data["height"][index]) / scale
        tokens.append(
            {
                "text": str(text),
                "value": value,
                "confidence": confidence,
                "cx": left + width / 2,
                "cy": top + height / 2,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        )
    return tokens


def ocr_text_tokens(image: np.ndarray, *, min_confidence: float = 35) -> list[dict]:
    if pytesseract is None:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = 2
    enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    try:
        data = pytesseract.image_to_data(enlarged, config="--psm 6", output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    tokens: list[dict] = []
    for index, text in enumerate(data.get("text", [])):
        cleaned = str(text).strip().translate(TEXT_TRANSLATION)
        if not cleaned or parse_numeric_token(cleaned) is not None:
            continue
        try:
            confidence = float(data["conf"][index])
        except Exception:
            confidence = -1.0
        if confidence < min_confidence:
            continue
        left = float(data["left"][index]) / scale
        top = float(data["top"][index]) / scale
        width = float(data["width"][index]) / scale
        height = float(data["height"][index]) / scale
        tokens.append(
            {
                "text": cleaned,
                "confidence": confidence,
                "cx": left + width / 2,
                "cy": top + height / 2,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        )
    return tokens


def infer_axis_labels_from_ocr(image: np.ndarray, area: tuple[int, int, int, int]) -> dict:
    x0, y0, x1, y1 = area
    height, width = image.shape[:2]
    x_region = image[max(0, y1 - 8) : min(height, y1 + 72), max(0, x0 - 8) : min(width, x1 + 8)]
    y_region = image[max(0, y0 - 8) : min(height, y1 + 8), max(0, x0 - 95) : min(width, x0 + 22)]
    x_text = _join_tokens(ocr_text_tokens(x_region, min_confidence=25))
    y_text = _join_tokens(ocr_text_tokens(_rotate_for_y_axis(y_region), min_confidence=25))
    x_label, x_unit = _parse_axis_label(x_text)
    y_label, y_unit = _parse_axis_label(y_text)
    return {
        "x_axis_label": x_label,
        "x_axis_unit": x_unit,
        "y_axis_label": y_label,
        "y_axis_unit": y_unit,
    }


def _rotate_for_y_axis(image: np.ndarray) -> np.ndarray:
    return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)


def _join_tokens(tokens: list[dict]) -> str:
    return " ".join(str(token["text"]) for token in sorted(tokens, key=lambda item: (float(item["top"]), float(item["left"]))))


def _parse_axis_label(text: str) -> tuple[str, str]:
    words = [_normalize_axis_word(word) for word in text.split()]
    words = [word for word in words if _keep_axis_word(word)]
    if not words:
        return "", ""
    normalized = " ".join(words)
    lower = normalized.lower()
    if "shear" in lower and "rate" in lower:
        return "Shear rate", _unit_from_text(normalized, "s^-1")
    if "time" in lower:
        return "Time", _unit_from_text(normalized, "s")
    if "viscosity" in lower:
        return "Viscosity", _unit_from_text(normalized, "mPa*s")
    if "strain" in lower:
        return "Strain", _unit_from_text(normalized, "%")
    if "storage" in lower and "modulus" in lower:
        return "Storage Modulus G'", _unit_from_text(normalized, "kPa")
    if "g'" in lower or "g''" in lower:
        return "G' and G''", _unit_from_text(normalized, "Pa")
    if "od" in lower and "600" in lower:
        return "Bacteria OD600", ""
    if "phenol" in lower:
        return "Phenol", "%"
    label_words = [word for word in words if not _looks_like_unit(word)]
    unit = _unit_from_text(normalized, "")
    return (" ".join(label_words) or normalized, unit)


def _normalize_axis_word(word: str) -> str:
    return word.strip("[]{}|,:;").translate(TEXT_TRANSLATION)


def _keep_axis_word(word: str) -> bool:
    if not word:
        return False
    lowered = word.lower()
    if lowered in {"legend", "plot", "grid", "flink"}:
        return False
    return any(ch.isalpha() for ch in word) or "'" in word or "%" in word or "^-1" in word


def _looks_like_unit(word: str) -> bool:
    return word in {"%", "Pa", "mPa*s", "s", "s^-1"} or word.startswith("(")


def _unit_from_text(text: str, fallback: str) -> str:
    lower = text.lower()
    if "kpa" in lower:
        return "kPa"
    if "mpa" in lower:
        return "mPa*s"
    if fallback == "mPa*s" and "pa" in lower:
        return "mPa*s"
    if "pa" in lower:
        return "Pa"
    if "s^-1" in lower or "s-1" in lower:
        return "s^-1"
    if "hour" in lower:
        return "hours"
    if re_search_word(lower, "s"):
        return "s"
    if "%" in text:
        return "%"
    return fallback


def re_search_word(text: str, word: str) -> bool:
    return any(part.strip("()") == word for part in text.split())


def dedupe_ticks(ticks: list[tuple[float, float]], axis: str) -> list[tuple[float, float]]:
    if not ticks:
        return []
    ticks = sorted(ticks, key=lambda item: item[0])
    unique: list[tuple[float, float]] = []
    for pixel, value in ticks:
        if unique and abs(unique[-1][0] - pixel) < 8:
            if abs(value) > abs(unique[-1][1]):
                unique[-1] = (pixel, value)
            continue
        unique.append((pixel, value))
    if axis == "y":
        unique = sorted(unique, key=lambda item: item[0])
    return unique


def fit_linear(pixels: list[float], values: list[float]) -> tuple[float, float] | None:
    if len(pixels) < 2 or len(set(values)) < 2:
        return None
    coef = np.polyfit(np.array(pixels, dtype=float), np.array(values, dtype=float), 1)
    return (float(coef[0]), float(coef[1]))


def linear_transform_from_ticks(ticks: list[tuple[float, float]]) -> dict | None:
    fit = fit_linear([tick[0] for tick in ticks], [tick[1] for tick in ticks])
    if not fit:
        return None
    return {"scale": "linear", "a": fit[0], "b": fit[1], "ticks": ticks}


def fit_log(pixels: list[float], values: list[float]) -> tuple[float, float] | None:
    positive = [(p, v) for p, v in zip(pixels, values) if v > 0]
    if len(positive) < 2:
        return None
    p_arr = np.array([p for p, _value in positive], dtype=float)
    v_arr = np.log10(np.array([value for _pixel, value in positive], dtype=float))
    coef = np.polyfit(p_arr, v_arr, 1)
    return (float(coef[0]), float(coef[1]))


def infer_axis_transform(ticks: list[tuple[float, float]], axis: str) -> dict | None:
    ticks = dedupe_ticks(ticks, axis)
    if len(ticks) < 2:
        return None
    pixels = [tick[0] for tick in ticks]
    values = [tick[1] for tick in ticks]
    positive_values = [value for value in values if value > 0]
    log_candidate = len(positive_values) >= 2 and max(positive_values) / max(min(positive_values), 1e-12) >= 100
    if log_candidate:
        fit = fit_log(pixels, values)
        if fit:
            return {"scale": "log10", "a": fit[0], "b": fit[1], "ticks": ticks}
    fit = fit_linear(pixels, values)
    if fit:
        return {"scale": "linear", "a": fit[0], "b": fit[1], "ticks": ticks}
    return None


def apply_transform(transform: dict | None, pixel: float) -> float | None:
    if not transform:
        return None
    value = float(transform["a"]) * pixel + float(transform["b"])
    if transform.get("scale") == "log10":
        return 10 ** value
    return value


def axis_calibration_from_ocr(image: np.ndarray, area: tuple[int, int, int, int]) -> dict:
    x0, y0, x1, y1 = area
    tokens = ocr_numeric_tokens(image)
    x_ticks: list[tuple[float, float]] = []
    y_left_ticks: list[tuple[float, float]] = []
    y_right_ticks: list[tuple[float, float]] = []
    for token in tokens:
        cx = float(token["cx"])
        cy = float(token["cy"])
        value = float(token["value"])
        confidence = float(token.get("confidence") or 0)
        if x0 - 8 <= cx <= x1 + 8 and y1 + 2 <= cy <= y1 + 55:
            x_ticks.append((cx, value))
        if confidence >= 50 and x0 - 35 <= cx <= x0 - 3 and y0 - 5 <= cy <= y1 + 5:
            y_left_ticks.append((cy, value))
        if confidence >= 50 and x1 + 3 <= cx <= x1 + 45 and y0 - 5 <= cy <= y1 + 5:
            y_right_ticks.append((cy, value))
    return {
        "x": infer_axis_transform(x_ticks, "x"),
        "y_left": infer_axis_transform(y_left_ticks, "y"),
        "y_right": infer_axis_transform(y_right_ticks, "y"),
    }
