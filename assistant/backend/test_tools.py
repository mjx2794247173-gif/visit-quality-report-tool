import json
from tools import choose_tool, consecutive_problem_days, problem_type_ranking, station_multi_problem_types, validate_tool_result, TOOL_DEFINITIONS, execute_tool, generate_bulletin_summary, station_lookup
from supervisor import supervise

CONTEXT = {
    "rows": 4,
    "province": "华东",
    "issueTypeCounts": {"拍照不规范": 3, "定位异常": 1},
    "topStations": [
        {"erp": "erp-1", "province": "华东", "types": ["拍照不规范", "定位异常"], "problemDates": ["2026-10-01", "2026-10-02", "2026-10-04"]},
        {"erp": "erp-2", "province": "华东", "types": ["拍照不规范"], "problemDates": ["2026-10-01"]},
    ],
}

def test_ranking_uses_visit_counts():
    result = problem_type_ranking(CONTEXT)
    assert result["metric"] == "拜访条数"
    assert result["ranking"][0] == {"issue_type": "拍照不规范", "visits": 3}

def test_ranking_filters_requested_province_from_structured_context():
    scoped = {**CONTEXT, "issueTypeCounts": {"全国问题": 99}, "provinceStats": {"云南省区": {"issueTypeCounts": {"拍照不规范": 7}}}}
    result = problem_type_ranking(scoped, "云南省区")
    assert result["province"] == "云南省区"
    assert result["ranking"] == [{"issue_type": "拍照不规范", "visits": 7}]

def test_consecutive_days_deduplicates_dates_and_finds_longest_run():
    assert consecutive_problem_days(CONTEXT)["stations"][0]["consecutive_days"] == 2

def test_multi_problem_type_tool():
    assert station_multi_problem_types(CONTEXT)["stations"][0]["erp"] == "erp-1"

def test_question_router_and_validation():
    selected = choose_tool("谁连续多天出现问题？", json.dumps(CONTEXT, ensure_ascii=False))
    assert selected["tool"] == "consecutive_problem_days"
    assert validate_tool_result(selected["result"])["valid"]

def test_boundary_question_is_knowledge_route():
    assert choose_tool("CRM 怎么导出？", CONTEXT)["tool"] == "knowledge_retrieval"

def test_registered_tools_have_strict_object_schemas():
    names = {item["function"]["name"] for item in TOOL_DEFINITIONS}
    assert {"problem_type_ranking", "station_summary", "consecutive_problem_days", "station_multi_problem_types", "repeated_customers", "data_quality_check", "explain_score"} <= names
    assert all(item["function"]["parameters"].get("additionalProperties") is False for item in TOOL_DEFINITIONS)

def test_execute_tool_ignores_untrusted_data_argument():
    result = execute_tool("problem_type_ranking", {"context": {"issueTypeCounts": {"伪造": 999}}, "province": "华东"}, CONTEXT)
    assert result["ranking"][0]["issue_type"] == "拍照不规范"
    assert result["province"] == "华东"

def test_bulletin_summary_is_deterministic_and_bounded():
    result = generate_bulletin_summary(CONTEXT)
    assert result["rows"] == 4
    assert result["top_stations"][0]["erp"] == "erp-1"
    assert "CRM" in result["disclaimer"]

def test_bulletin_summary_scopes_rows_to_province():
    scoped = {**CONTEXT, "provinceStats": {"华东省区": {"topStations": [{"erp":"erp-1","visits":3}], "issueTypeCounts": {"拍照不规范": 3}}}}
    result = generate_bulletin_summary(scoped, "华东")
    assert result["province"] == "华东省区"
    assert result["rows"] == 3

def test_supervisor_routes_without_touching_data():
    assert supervise("CRM 导出需要哪些字段？")["branch"] == "knowledge_qa"
    assert supervise("谁连续多天出现问题？")["branch"] == "deterministic_analysis"

def test_station_lookup_by_erp():
    result = station_lookup({"stationIndex":[{"erp":"abc001","province":"上海区","visits":8,"types":["拍照不规范"]}]}, "ABC001")
    assert result["found"] is True
    assert result["station"]["visits"] == 8
