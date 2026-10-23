import json
from tools import attach_erp_lookup, choose_tool, consecutive_problem_days, extract_erp, problem_type_ranking, station_multi_problem_types, validate_tool_result, validate_tool_result_against_plan, TOOL_DEFINITIONS, execute_tool, generate_bulletin_summary, station_lookup, has_date_condition
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

def test_validate_tool_result_against_plan_rejects_tampered_scope():
    plan = {"filters": {"province": "广东省区"}, "group_by": "station_erp", "metric": "visit_count", "order": "desc", "limit": 5}
    result = {"tool": "spreadsheet_query", "scope": {**plan, "limit": 10}, "rows": [], "facets": {"issue_types": [], "stations": [], "station_province_counts": []}}
    validation = validate_tool_result_against_plan("spreadsheet_query", plan, result)
    assert validation["valid"] is False
    assert "limit" in validation["errors"][0]


def test_validate_tool_result_requires_multidimensional_facets():
    plan = {"filters": {}, "group_by": "issue_type", "metric": "visit_count", "order": "desc", "limit": 10}
    result = {"tool": "spreadsheet_query", "scope": plan, "rows": []}

    validation = validate_tool_result_against_plan("spreadsheet_query", plan, result)

    assert validation["valid"] is False
    assert "表格查询结果缺少 facets" in validation["errors"]

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


def test_standalone_erp_routes_to_lookup():
    context = '{"stationIndex":[{"erp":"shizhuangzhuang","province":"浙江省区","visits":4,"types":["拍照不规范"]}]}'
    selected = choose_tool("shizhuangzhuang", context)
    assert extract_erp("查询 shizhuangzhuang 的问题") == "shizhuangzhuang"
    assert selected["tool"] == "station_lookup"
    assert selected["result"]["found"] is True


def test_station_subject_queries_do_not_route_to_issue_type_ranking():
    assert choose_tool("找出虚假的站长", CONTEXT)["tool"] == "station_summary"
    assert choose_tool("哪些站长问题最多？", CONTEXT)["tool"] == "station_summary"
    assert choose_tool("哪类问题最多？", CONTEXT)["tool"] == "problem_type_ranking"


def test_exact_station_date_issue_count_routes_to_deterministic_tool():
    context = {"queryDetail": {"erp": "liheng105", "date": "2026-10-12", "issue_type": "录入内容重复", "visits": 3, "matched": True}}
    selected = choose_tool("liheng105 在 2026-10-12 录入内容重复多少次？", context)
    assert selected["tool"] == "station_issue_date_count"
    assert selected["result"]["visits"] == 3


def test_natural_language_date_variants_are_recognized():
    for question in ("10-12 哪个站长问题最多", "10月12日哪个站长违规最多", "10/12 谁最多", "2026年10月12日哪个站长次数最多", "当天哪个站长最多"):
        assert has_date_condition(question)


def test_implicit_top_n_defaults_to_station_ranking():
    assert choose_tool("10/09 全国虚假前五", CONTEXT)["tool"] == "station_summary"
    assert choose_tool("全国问题类型前五", CONTEXT)["tool"] == "problem_type_ranking"
    result = execute_tool("station_summary", {"top_n": 1}, CONTEXT)
    assert len(result["stations"]) == 1


def test_explicit_empty_erp_index_does_not_fall_back_to_top_stations():
    result = station_lookup({"stationIndex": [], "topStations": [{"erp": "abc001"}]}, "abc001")
    assert result["found"] is False


def test_query_scoped_erp_lookup_replaces_summary_index():
    context = attach_erp_lookup('{"stationIndex":[],"rows":10}', [{"erp":"abc001","visits":3}])
    assert station_lookup(context, "abc001")["found"] is True
