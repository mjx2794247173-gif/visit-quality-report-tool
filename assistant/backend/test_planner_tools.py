import asyncio

import pytest
from pydantic import ValidationError

from assistant.backend.main import AgentDecision, EmptyToolPlan, KnowledgePlan, MULTI_AGENT_GRAPH, PLANNER_TOOLS, RetrievalAssessment, RetrievalRanking, RetrievalRewrite, SpreadsheetPlan, apply_source_ranking, assess_retrieval_sufficiency, filter_ranked_sources, merge_retrieval_sources, reciprocal_rank_fusion


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


def test_retrieval_assessment_requires_a_complete_bounded_decision():
    decision = RetrievalAssessment.model_validate({
        "is_sufficient": False,
        "missing_information": "缺少评分公式",
    })
    assert decision.is_sufficient is False
    with pytest.raises(ValidationError):
        RetrievalAssessment.model_validate({"is_sufficient": True})
    with pytest.raises(ValidationError):
        RetrievalAssessment.model_validate({
            "is_sufficient": False,
            "missing_information": "x" * 501,
        })


def test_retrieval_assessment_rejects_model_invented_fields():
    with pytest.raises(ValidationError):
        RetrievalAssessment.model_validate({
            "is_sufficient": True,
            "missing_information": "",
            "answer": "模型擅自生成的答案",
        })


def test_empty_retrieval_is_always_insufficient_without_calling_model():
    decision = asyncio.run(assess_retrieval_sufficiency("未知制度是什么", []))
    assert decision.is_sufficient is False
    assert "未检索到" in decision.missing_information


def test_retrieval_rewrite_requires_one_bounded_query_only():
    assert RetrievalRewrite.model_validate({"query": "重点站长评分公式"}).query == "重点站长评分公式"
    with pytest.raises(ValidationError):
        RetrievalRewrite.model_validate({"query": ""})
    with pytest.raises(ValidationError):
        RetrievalRewrite.model_validate({"query": "评分公式", "answer": "额外答案"})


def test_supplemental_retrieval_merges_and_deduplicates_sources():
    first = [{"source": "a.md", "text": "第一段"}]
    second = [
        {"source": "a.md", "text": "第一段"},
        {"source": "b.md", "text": "第二段"},
    ]
    assert merge_retrieval_sources(first, second) == [
        {"source": "a.md", "text": "第一段"},
        {"source": "b.md", "text": "第二段"},
    ]


def test_hybrid_fusion_rewards_documents_found_by_both_retrievers():
    semantic = [
        {"source": "semantic.md", "text": "只被语义召回"},
        {"source": "shared.md", "text": "两边都召回"},
    ]
    lexical = [
        {"source": "lexical.md", "text": "只被关键词召回"},
        {"source": "shared.md", "text": "两边都召回"},
    ]
    result = reciprocal_rank_fusion([semantic, lexical], limit=3)
    assert result[0] == {"source": "shared.md", "text": "两边都召回"}
    assert {item["source"] for item in result} == {"semantic.md", "lexical.md", "shared.md"}


def test_hybrid_fusion_deduplicates_and_obeys_limit():
    duplicate = {"source": "same.md", "text": "同一段"}
    result = reciprocal_rank_fusion([[duplicate], [duplicate]], limit=1)
    assert result == [duplicate]


def test_source_ranking_can_only_reorder_existing_evidence():
    sources = [
        {"source": "a.md", "text": "A"},
        {"source": "b.md", "text": "B"},
        {"source": "c.md", "text": "C"},
    ]
    ranking = RetrievalRanking.model_validate({"ranked_indices": [2, 0, 1], "relevant_indices": [2, 0]})
    assert apply_source_ranking(sources, ranking) == [sources[2], sources[0], sources[1]]
    assert filter_ranked_sources(sources, ranking) == [sources[2], sources[0]]


@pytest.mark.parametrize("indices", [[0, 0, 1], [0, 1], [0, 1, 3]])
def test_source_ranking_rejects_duplicates_missing_or_unknown_indices(indices):
    sources = [
        {"source": "a.md", "text": "A"},
        {"source": "b.md", "text": "B"},
        {"source": "c.md", "text": "C"},
    ]
    with pytest.raises(ValueError):
        apply_source_ranking(sources, RetrievalRanking.model_validate({"ranked_indices": indices, "relevant_indices": []}))


def test_relevance_filter_must_be_a_ranked_prefix():
    sources = [
        {"source": "a.md", "text": "A"},
        {"source": "b.md", "text": "B"},
        {"source": "c.md", "text": "C"},
    ]
    ranking = RetrievalRanking.model_validate({"ranked_indices": [2, 0, 1], "relevant_indices": [2, 1]})
    with pytest.raises(ValueError):
        filter_ranked_sources(sources, ranking)


def test_relevance_filter_can_reject_all_candidates():
    sources = [{"source": "a.md", "text": "A"}, {"source": "b.md", "text": "B"}]
    ranking = RetrievalRanking.model_validate({"ranked_indices": [1, 0], "relevant_indices": []})
    assert filter_ranked_sources(sources, ranking) == []


def test_source_ranking_rejects_extra_model_output():
    with pytest.raises(ValidationError):
        RetrievalRanking.model_validate({"ranked_indices": [0], "relevant_indices": [0], "answer": "额外答案"})


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
