import asyncio
import json
import sqlite3
import threading

import pytest
from pydantic import ValidationError

from assistant.backend.main import AgentDecision, AnswerRequest, EmptyToolPlan, KnowledgePlan, MULTI_AGENT_GRAPH, PLANNER_TOOLS, RetrievalAssessment, RetrievalRanking, RetrievalRewrite, SpreadsheetPlan, WorkingMemory, _retrieval_cache, apply_source_ranking, assess_retrieval_sufficiency, audit, clear_retrieval_cache, filter_ranked_sources, load_working_memory, merge_retrieval_sources, plan_signature, reciprocal_rank_fusion, retrieve, retrieve_async, save_pending_workflow, load_pending_workflow, save_working_memory, update_working_memory


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


def test_audit_log_keeps_only_safe_operational_metadata(tmp_path, monkeypatch):
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr("assistant.backend.main.AUDIT_LOG", audit_file)
    audit({
        "action": "answer",
        "ok": True,
        "tool": "knowledge_retrieval",
        "source_count": 3,
        "trace_id": "a" * 32,
        "question": "不应记录的用户问题",
        "rows": [{"customer": "不应记录的客户"}],
        "answer": "不应记录的回答正文",
    })
    saved = json.loads(audit_file.read_text(encoding="utf-8"))
    assert saved["action"] == "answer"
    assert saved["source_count"] == 3
    assert saved["trace_id"] == "a" * 32
    assert "question" not in saved
    assert "rows" not in saved
    assert "answer" not in saved


def test_answer_trace_id_must_be_anonymous_hex_identifier():
    payload = {"question":"测试", "plan":{}, "tool_result":{"tool":"data_quality_check"}, "session_id":"b" * 32}
    assert AnswerRequest.model_validate({**payload, "trace_id":"a" * 32}).trace_id == "a" * 32
    with pytest.raises(ValidationError):
        AnswerRequest.model_validate({**payload, "trace_id":"customer-name"})


def test_plan_signature_is_stable_and_changes_when_plan_changes():
    base = {"filters": {"province": "广东省区"}, "group_by": "station_erp", "metric": "visit_count", "order": "desc", "limit": 5}
    first = plan_signature("a" * 32, "b" * 32, "问题", "spreadsheet_query", base)
    assert first == plan_signature("a" * 32, "b" * 32, "问题", "spreadsheet_query", dict(base))
    assert len(first) == 64
    changed = {**base, "limit": 4}
    assert first != plan_signature("a" * 32, "b" * 32, "问题", "spreadsheet_query", changed)


def test_working_memory_keeps_only_validated_query_conditions():
    memory = update_working_memory({}, "spreadsheet_query", {
        "filters":{"province":"广东省区", "date_from":"2026-10-12"},
        "group_by":"station_erp", "metric":"visit_count", "order":"desc", "limit":5,
    })
    assert memory["filters"]["province"] == "广东省区"
    assert memory["filters"]["date_from"] == "2026-10-12"
    assert memory["group_by"] == "station_erp"
    assert "rows" not in memory
    assert "answer" not in memory


def test_non_data_turn_preserves_query_conditions_and_updates_last_tool():
    existing = WorkingMemory(
        last_tool="spreadsheet_query", filters={"province":"浙江省区"},
        group_by="issue_type", metric="visit_count", order="desc", limit=10,
    ).model_dump(exclude_none=True)
    memory = update_working_memory(existing, "knowledge_retrieval", {"query":"统计口径"})
    assert memory["last_tool"] == "knowledge_retrieval"
    assert memory["filters"]["province"] == "浙江省区"
    assert memory["group_by"] == "issue_type"


def test_working_memory_rejects_unvalidated_fields():
    with pytest.raises(ValidationError):
        WorkingMemory.model_validate({"last_tool":"spreadsheet_query", "rows":[{"customer":"secret"}]})


def test_persisted_memory_hashes_session_and_removes_erp(tmp_path, monkeypatch):
    database = tmp_path / "memory.sqlite3"
    monkeypatch.setattr("assistant.backend.main.MEMORY_DB", database)
    memory = update_working_memory({}, "spreadsheet_query", {
        "filters":{"province":"广东省区", "station_erp":"employee123"},
        "group_by":"station_erp", "metric":"visit_count", "order":"desc", "limit":5,
    })
    save_working_memory("visible-browser-session", memory)
    loaded = load_working_memory("visible-browser-session")
    assert loaded["filters"]["province"] == "广东省区"
    assert loaded["filters"].get("station_erp") is None
    raw = database.read_bytes()
    assert b"visible-browser-session" not in raw
    assert b"employee123" not in raw


def test_expired_persisted_memory_is_not_restored(tmp_path, monkeypatch):
    database = tmp_path / "memory.sqlite3"
    monkeypatch.setattr("assistant.backend.main.MEMORY_DB", database)
    save_working_memory("expired-session", WorkingMemory(last_tool="data_quality_check").model_dump(exclude_none=True))
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE session_memory SET updated_at = 0")
    assert load_working_memory("expired-session") == {}


def test_pending_workflow_persists_only_binding_metadata(tmp_path, monkeypatch):
    database = tmp_path / "memory.sqlite3"
    monkeypatch.setattr("assistant.backend.main.MEMORY_DB", database)
    save_pending_workflow("session-a", {
        "workflow_id": "a" * 32,
        "signature": "b" * 64,
        "plan": {"filters": {"station_erp": "employee123"}},
    })
    loaded = load_pending_workflow("session-a")
    assert loaded == {"workflow_id": "a" * 32, "signature": "b" * 64}
    raw = database.read_bytes()
    assert b"employee123" not in raw
    assert b"plan" not in raw


def test_retrieval_cache_reuses_results_without_plaintext_query(monkeypatch):
    clear_retrieval_cache()
    calls = []
    monkeypatch.setattr("assistant.backend.main._retrieve_uncached", lambda question, limit: calls.append((question, limit)) or [{"source":"rules.md", "text":"result"}])
    first = retrieve("敏感查询原文", 6)
    first[0]["text"] = "mutated"
    second = retrieve("敏感查询原文", 6)
    assert calls == [("敏感查询原文", 6)]
    assert second[0]["text"] == "result"
    assert all("敏感查询原文" not in key for key in _retrieval_cache)
    clear_retrieval_cache()


def test_retrieval_cache_expires_after_ttl(monkeypatch):
    clear_retrieval_cache()
    clock = {"now": 100.0}
    calls = []
    monkeypatch.setattr("assistant.backend.main.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr("assistant.backend.main.RETRIEVAL_CACHE_TTL_SECONDS", 10)
    monkeypatch.setattr("assistant.backend.main._retrieve_uncached", lambda question, limit: calls.append(question) or [{"source":"rules.md", "text":question}])
    retrieve("评分规则")
    clock["now"] = 111.0
    retrieve("评分规则")
    assert calls == ["评分规则", "评分规则"]
    clear_retrieval_cache()


def test_async_retrieval_runs_blocking_work_in_worker_thread(monkeypatch):
    caller_thread = threading.get_ident()
    worker_threads = []
    monkeypatch.setattr("assistant.backend.main.retrieve", lambda question, limit: worker_threads.append(threading.get_ident()) or [{"source":"rules.md", "text":question}])
    result = asyncio.run(retrieve_async("评分规则"))
    assert result[0]["text"] == "评分规则"
    assert worker_threads and worker_threads[0] != caller_thread


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
