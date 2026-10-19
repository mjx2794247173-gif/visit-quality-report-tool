import json
from pathlib import Path

from assistant.backend.evaluation import matches_subset, score_plan_result, summarize_evaluation


CASES_PATH = Path(__file__).with_name("eval_cases.json")


def test_eval_cases_cover_every_specialist_agent():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    assert len(cases) >= 8
    assert {case["expected_agent"] for case in cases} == {
        "data_agent",
        "knowledge_agent",
        "quality_agent",
        "publishing_agent",
    }
    assert len({case["id"] for case in cases}) == len(cases)


def test_matches_subset_supports_nested_plan_fields():
    actual = {
        "filters": {"province": "广东省区", "issue_type": None},
        "limit": 5,
        "ignored": "allowed",
    }
    assert matches_subset(actual, {"filters": {"province": "广东省区"}, "limit": 5})
    assert not matches_subset(actual, {"filters": {"province": "浙江省区"}})


def test_score_plan_result_identifies_each_failure_layer():
    case = {
        "expected_agent": "data_agent",
        "expected_tool": "spreadsheet_query",
        "expected_plan_subset": {"limit": 5},
    }
    score = score_plan_result(
        {"agent": "knowledge_agent", "tool": "knowledge_retrieval", "plan": {"limit": 10}},
        case,
    )
    assert score["passed"] is False
    assert score["failed_checks"] == ["agent", "tool", "plan"]


def test_evaluation_summary_separates_quality_latency_and_request_failures():
    metrics = summarize_evaluation([
        {
            "request_ok": True,
            "elapsed_ms": 100,
            "score": {
                "passed": True,
                "checks": {"agent": True, "tool": True, "plan": True},
            },
        },
        {
            "request_ok": True,
            "elapsed_ms": 300,
            "score": {
                "passed": False,
                "checks": {"agent": True, "tool": False, "plan": False},
            },
        },
        {"request_ok": False, "elapsed_ms": 50},
    ])
    assert metrics == {
        "total": 3,
        "completed": 2,
        "agent_accuracy": 1.0,
        "tool_accuracy": 0.5,
        "plan_accuracy": 0.5,
        "overall_accuracy": 0.5,
        "request_failure_rate": 0.3333,
        "average_elapsed_ms": 200.0,
    }


def test_empty_evaluation_summary_is_safe():
    assert summarize_evaluation([]) == {
        "total": 0,
        "completed": 0,
        "agent_accuracy": 0.0,
        "tool_accuracy": 0.0,
        "plan_accuracy": 0.0,
        "overall_accuracy": 0.0,
        "request_failure_rate": 0.0,
        "average_elapsed_ms": 0.0,
    }
