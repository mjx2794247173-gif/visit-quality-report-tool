"""Small, deterministic scoring helpers for planner evaluation cases."""
from __future__ import annotations

from typing import Any


def matches_subset(actual: Any, expected: Any) -> bool:
    """Return whether every expected value exists recursively in actual."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches_subset(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            matches_subset(actual_value, expected_value)
            for actual_value, expected_value in zip(actual, expected)
        )
    return actual == expected


def score_plan_result(actual: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Score routing, tool selection and important plan fields separately."""
    checks = {
        "agent": actual.get("agent") == case.get("expected_agent"),
        "tool": actual.get("tool") == case.get("expected_tool"),
        "plan": matches_subset(
            actual.get("plan", {}),
            case.get("expected_plan_subset", {}),
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
