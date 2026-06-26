from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PropertyContract:
    property_name: str
    expected_units: list[str] = field(default_factory=list)
    numerical_constraints: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


CONTRACT_REGISTRY: dict[str, PropertyContract] = {}


def register(contract: PropertyContract) -> None:
    CONTRACT_REGISTRY[contract.property_name] = contract


def get_contract(property_name: str) -> PropertyContract | None:
    return CONTRACT_REGISTRY.get(property_name)


def validate_unit(property_name: str, unit: str) -> bool:
    contract = get_contract(property_name)
    if not contract or not contract.expected_units:
        return True
    return unit.strip().lower() in {u.strip().lower() for u in contract.expected_units}


def validate_numeric(property_name: str, value: float) -> list[str]:
    contract = get_contract(property_name)
    if not contract:
        return []
    violations: list[str] = []
    for constraint in contract.numerical_constraints:
        try:
            if not _evaluate_constraint(constraint, value):
                violations.append(constraint)
        except Exception:
            violations.append(constraint)
    return violations


def _evaluate_constraint(constraint: str, value: float) -> bool:
    constraint = constraint.strip()
    if ">" in constraint and "<" in constraint:
        parts = constraint.replace("value", str(value))
        return eval(parts, {"__builtins__": {}}, {})
    expr = constraint.replace("value", str(value))
    return bool(eval(expr, {"__builtins__": {}}, {}))
