from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

from app.services.chart_extraction.contracts import Contract

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    rule: str
    severity: str
    message: str
    point_index: int = -1


@dataclass
class ValidationResult:
    passed: bool
    confidence: float
    issues: list[ValidationIssue] = field(default_factory=list)


class NumericalValidator:
    """Pure-rule validation. Zero LLM calls."""

    def validate(self, points: list[dict], contract: Contract) -> ValidationResult:
        issues: list[ValidationIssue] = []

        issues.extend(self._rule_null_values(points))
        issues.extend(self._rule_log_axis_positive(points, contract))
        issues.extend(self._rule_axis_range(points, contract))
        issues.extend(self._rule_unit_consistency(points, contract))
        issues.extend(self._rule_monotonicity(points))
        issues.extend(self._rule_series_name_quality(points))
        issues.extend(self._rule_minimum_density(points))
        issues.extend(self._rule_outliers(points))
        issues.extend(self._rule_error_bar_format(points))
        issues.extend(self._rule_contract_constraints(points, contract))

        has_errors = any(i.severity == "error" for i in issues)
        confidence = self._compute_confidence(points, issues)

        return ValidationResult(
            passed=not has_errors,
            confidence=confidence,
            issues=issues,
        )

    def _rule_null_values(self, points: list[dict]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for idx, pt in enumerate(points):
            x = pt.get("x_value")
            y = pt.get("y_value")
            if x is None or y is None:
                issues.append(ValidationIssue(
                    rule="null_value",
                    severity="error",
                    message=f"Point {idx}: null x or y value",
                    point_index=idx,
                ))
            elif isinstance(x, float) and math.isnan(x):
                issues.append(ValidationIssue(
                    rule="nan_value",
                    severity="error",
                    message=f"Point {idx}: NaN x_value",
                    point_index=idx,
                ))
            elif isinstance(y, float) and math.isnan(y):
                issues.append(ValidationIssue(
                    rule="nan_value",
                    severity="error",
                    message=f"Point {idx}: NaN y_value",
                    point_index=idx,
                ))
        return issues

    def _rule_log_axis_positive(self, points: list[dict], contract: Contract) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if contract.x_axis.scale == "log10":
            for idx, pt in enumerate(points):
                x = pt.get("x_value")
                if x is not None:
                    try:
                        if float(x) <= 0:
                            issues.append(ValidationIssue(
                                rule="log_axis_non_positive",
                                severity="error",
                                message=f"Point {idx}: x_value={x} <= 0 on log10 x-axis",
                                point_index=idx,
                            ))
                    except (TypeError, ValueError):
                        pass
        if contract.y_axis.scale == "log10":
            for idx, pt in enumerate(points):
                y = pt.get("y_value")
                if y is not None:
                    try:
                        if float(y) <= 0:
                            issues.append(ValidationIssue(
                                rule="log_axis_non_positive",
                                severity="error",
                                message=f"Point {idx}: y_value={y} <= 0 on log10 y-axis",
                                point_index=idx,
                            ))
                    except (TypeError, ValueError):
                        pass
        return issues

    def _rule_axis_range(self, points: list[dict], contract: Contract) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        tolerance = 0.2

        x_min = contract.x_axis.range_hint_min
        x_max = contract.x_axis.range_hint_max
        if x_min is not None:
            lower = x_min * (1 - tolerance) if x_min > 0 else x_min - abs(x_min) * tolerance
            for idx, pt in enumerate(points):
                try:
                    if float(pt.get("x_value", 0)) < lower:
                        issues.append(ValidationIssue(
                            rule="range_violation",
                            severity="warning",
                            message=f"Point {idx}: x_value below expected range ({x_min})",
                            point_index=idx,
                        ))
                except (TypeError, ValueError):
                    pass
        if x_max is not None:
            upper = x_max * (1 + tolerance)
            for idx, pt in enumerate(points):
                try:
                    if float(pt.get("x_value", 0)) > upper:
                        issues.append(ValidationIssue(
                            rule="range_violation",
                            severity="warning",
                            message=f"Point {idx}: x_value above expected range ({x_max})",
                            point_index=idx,
                        ))
                except (TypeError, ValueError):
                    pass
        return issues

    def _rule_unit_consistency(self, points: list[dict], contract: Contract) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not contract.x_axis.unit and not contract.y_axis.unit:
            return issues

        for idx, pt in enumerate(points):
            pt_x_unit = str(pt.get("x_unit") or "").strip()
            pt_y_unit = str(pt.get("y_unit") or "").strip()
            if contract.x_axis.unit and pt_x_unit and pt_x_unit != contract.x_axis.unit:
                issues.append(ValidationIssue(
                    rule="unit_mismatch",
                    severity="warning",
                    message=f"Point {idx}: x_unit '{pt_x_unit}' != contract '{contract.x_axis.unit}'",
                    point_index=idx,
                ))
            if contract.y_axis.unit and pt_y_unit and pt_y_unit != contract.y_axis.unit:
                issues.append(ValidationIssue(
                    rule="unit_mismatch",
                    severity="warning",
                    message=f"Point {idx}: y_unit '{pt_y_unit}' != contract '{contract.y_axis.unit}'",
                    point_index=idx,
                ))
        return issues

    def _rule_monotonicity(self, points: list[dict]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        series_groups: dict[str, list[tuple[int, float]]] = {}
        for idx, pt in enumerate(points):
            series = str(pt.get("series_name") or pt.get("color_group") or "default")
            try:
                x = float(pt.get("x_value", 0))
            except (TypeError, ValueError):
                continue
            series_groups.setdefault(series, []).append((idx, x))

        for series_name, indexed_x in series_groups.items():
            if len(indexed_x) < 3:
                continue
            sorted_pts = sorted(indexed_x, key=lambda item: item[1])
            violations = 0
            for i in range(1, len(sorted_pts)):
                if sorted_pts[i][1] < sorted_pts[i - 1][1]:
                    violations += 1
            if violations > len(sorted_pts) * 0.3:
                issues.append(ValidationIssue(
                    rule="monotonicity",
                    severity="warning",
                    message=f"Series '{series_name}': {violations} monotonicity violations in {len(sorted_pts)} points",
                ))
        return issues

    def _rule_series_name_quality(self, points: list[dict]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        generic_names = set()
        for pt in points:
            name = str(pt.get("series_name") or "")
            if name.startswith("series_") or name.startswith("color_group") or name.startswith("series-"):
                generic_names.add(name)
        if generic_names:
            issues.append(ValidationIssue(
                rule="generic_series_name",
                severity="warning",
                message=f"Generic series names detected: {', '.join(sorted(generic_names))}",
            ))
        return issues

    def _rule_minimum_density(self, points: list[dict]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        series_counts: dict[str, int] = {}
        for pt in points:
            series = str(pt.get("series_name") or pt.get("color_group") or "default")
            series_counts[series] = series_counts.get(series, 0) + 1
        for series_name, count in series_counts.items():
            if count < 3:
                issues.append(ValidationIssue(
                    rule="minimum_density",
                    severity="warning",
                    message=f"Series '{series_name}': only {count} points (minimum 3 recommended)",
                ))
        return issues

    def _rule_outliers(self, points: list[dict]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        y_values: list[float] = []
        for pt in points:
            try:
                y_values.append(float(pt.get("y_value", 0)))
            except (TypeError, ValueError):
                continue
        if len(y_values) < 5:
            return issues

        mean_y = sum(y_values) / len(y_values)
        std_y = (sum((v - mean_y) ** 2 for v in y_values) / len(y_values)) ** 0.5
        if std_y < 1e-12:
            return issues

        for idx, pt in enumerate(points):
            try:
                y = float(pt.get("y_value", 0))
            except (TypeError, ValueError):
                continue
            z_score = abs(y - mean_y) / std_y
            if z_score > 3:
                issues.append(ValidationIssue(
                    rule="outlier",
                    severity="info",
                    message=f"Point {idx}: y_value={y} is {z_score:.1f}σ from mean ({mean_y:.2f})",
                    point_index=idx,
                ))
        return issues

    def _rule_error_bar_format(self, points: list[dict]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for idx, pt in enumerate(points):
            eb = pt.get("error_bar")
            if eb and str(eb).strip():
                try:
                    val = float(str(eb).strip().lstrip("±").strip())
                    if val < 0:
                        issues.append(ValidationIssue(
                            rule="error_bar_negative",
                            severity="warning",
                            message=f"Point {idx}: negative error_bar value: {eb}",
                            point_index=idx,
                        ))
                except (TypeError, ValueError):
                    if "±" not in str(eb) and "/" not in str(eb):
                        issues.append(ValidationIssue(
                            rule="error_bar_format",
                            severity="info",
                            message=f"Point {idx}: non-standard error_bar format: {eb}",
                            point_index=idx,
                        ))
        return issues

    _CONSTRAINT_RE = re.compile(r"^(?P<axis>[xy])_value\s*(?P<op>>=|>)\s*(?P<threshold>[\d.]+)$")
    _CONSTRAINT_OPS: dict[str, tuple[type, type]] = {
        ">":  (int, lambda v, t: v <= t),    # violate when value ≤ threshold
        ">=": (int, lambda v, t: v < t),     # violate when value < threshold
    }

    def _rule_contract_constraints(self, points: list[dict], contract: Contract) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for constraint in contract.numerical_constraints:
            m = self._CONSTRAINT_RE.match(constraint)
            if not m:
                continue
            axis, op_str, threshold = m.group("axis"), m.group("op"), float(m.group("threshold"))
            _, violates = self._CONSTRAINT_OPS[op_str]
            for idx, pt in enumerate(points):
                try:
                    val = float(pt.get(f"{axis}_value", 0))
                    if violates(val, threshold):
                        issues.append(ValidationIssue(
                            rule="contract_constraint",
                            severity="error",
                            message=f"Point {idx}: violates '{constraint}' (value={val})",
                            point_index=idx,
                        ))
                except (TypeError, ValueError):
                    pass
        return issues

    def _compute_confidence(self, points: list[dict], issues: list[ValidationIssue]) -> float:
        if not points:
            return 0.0
        error_count = sum(1 for i in issues if i.severity == "error")
        warning_count = sum(1 for i in issues if i.severity == "warning")
        base = 0.95
        penalty = error_count * 0.15 + warning_count * 0.05
        return max(0.0, min(1.0, base - penalty))
