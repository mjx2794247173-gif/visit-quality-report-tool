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


def summarize_evaluation(records: list[dict[str, Any]]) -> dict[str, float | int]:
    """Aggregate planner quality and reliability without retaining user questions."""
    total = len(records)
    successful = [record for record in records if record.get("request_ok")]
    scored = [record["score"] for record in successful if isinstance(record.get("score"), dict)]

    def accuracy(check_name: str) -> float:
        if not scored:
            return 0.0
        passed = sum(bool(score.get("checks", {}).get(check_name)) for score in scored)
        return round(passed / len(scored), 4)

    latencies = [
        float(record["elapsed_ms"])
        for record in successful
        if isinstance(record.get("elapsed_ms"), (int, float))
    ]
    return {
        "total": total,
        "completed": len(successful),
        "agent_accuracy": accuracy("agent"),
        "tool_accuracy": accuracy("tool"),
        "plan_accuracy": accuracy("plan"),
        "overall_accuracy": round(
            sum(bool(score.get("passed")) for score in scored) / len(scored), 4
        ) if scored else 0.0,
        "request_failure_rate": round((total - len(successful)) / total, 4) if total else 0.0,
        "average_elapsed_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
    }
