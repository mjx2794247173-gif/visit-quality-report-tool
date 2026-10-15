import pytest
from pydantic import ValidationError

from assistant.backend.main import AgentDecision, EmptyToolPlan, KnowledgePlan, MULTI_AGENT_GRAPH, PLANNER_TOOLS, SpreadsheetPlan


def test_planner_exposes_distinct_safe_capabilities():
    names = {item["function"]["name"] for item in PLANNER_TOOLS}
    assert names == {
        "spreadsheet_query",
        "knowledge_retrieval",
        "data_quality_check",
        "feishu_publish_preview",
    }


def test_planner_tool_schemas_reject_extra_arguments():
    assert all(
        item["function"]["parameters"].get("additionalProperties") is False
        for item in PLANNER_TOOLS
    )


def test_feishu_function_only_prepares_a_confirmed_preview():
    tool = next(
        item["function"]
        for item in PLANNER_TOOLS
        if item["function"]["name"] == "feishu_publish_preview"
    )
    assert "只准备内容" in tool["description"]
    assert tool["parameters"]["properties"] == {}


def test_langgraph_contains_supervisor_and_specialist_agents():
    nodes = set(MULTI_AGENT_GRAPH.get_graph().nodes)
    assert {
        "supervisor_agent",
        "data_agent",
        "knowledge_agent",
        "quality_agent",
        "publishing_agent",
    } <= nodes


def test_supervisor_decision_accepts_only_registered_agents():
    assert AgentDecision.model_validate({"agent": "data_agent"}).agent == "data_agent"
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({"agent": "unknown_agent"})


def test_supervisor_decision_requires_agent_field():
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({})


def test_spreadsheet_plan_normalizes_optional_filters():
    plan = SpreadsheetPlan.model_validate({
        "filters": {"province": "广东省区"},
        "group_by": "station_erp",
        "metric": "visit_count",
        "order": "desc",
        "limit": 5,
    })
    assert plan.filters.province == "广东省区"
    assert plan.filters.issue_type is None


@pytest.mark.parametrize("field,value", [
    ("group_by", "unknown_group"),
    ("metric", "model_guess"),
    ("order", "random"),
    ("limit", 0),
    ("limit", 51),
])
def test_spreadsheet_plan_rejects_invalid_query_contract(field, value):
    payload = {
        "filters": {},
        "group_by": "station_erp",
        "metric": "visit_count",
        "order": "desc",
        "limit": 5,
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        SpreadsheetPlan.model_validate(payload)


def test_knowledge_plan_requires_a_bounded_query():
    assert KnowledgePlan.model_validate({"query": "CRM导出字段"}).query == "CRM导出字段"
    with pytest.raises(ValidationError):
        KnowledgePlan.model_validate({"query": ""})
    with pytest.raises(ValidationError):
        KnowledgePlan.model_validate({"query": "x" * 501})


def test_no_argument_tools_reject_model_invented_parameters():
    assert EmptyToolPlan.model_validate({}).model_dump() == {}
    with pytest.raises(ValidationError):
        EmptyToolPlan.model_validate({"recipient": "someone@example.com"})


def test_all_agent_contracts_reject_unknown_fields():
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({"agent": "data_agent", "reason": "extra"})
    with pytest.raises(ValidationError):
        SpreadsheetPlan.model_validate({
            "filters": {}, "group_by": "station_erp", "metric": "visit_count",
            "order": "desc", "limit": 5, "sql": "select * from visits",
        })
