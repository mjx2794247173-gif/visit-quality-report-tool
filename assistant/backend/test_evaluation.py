import json
from pathlib import Path

from assistant.backend.evaluation import matches_subset, score_plan_result


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
