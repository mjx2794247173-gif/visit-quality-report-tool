"""Safe, read-only tools used by the assistant router.

These functions consume the browser's aggregated report context. They do not
read files, execute SQL, or decide whether a visit is fraudulent.
"""
from __future__ import annotations

import json
import re
from typing import Any
from datetime import date, timedelta


def _context(context: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(context, dict):
        return context
    try:
        value = json.loads(context or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def attach_erp_lookup(context: str, lookup: list[dict[str, Any]] | None) -> str:
    """Attach a query-scoped ERP aggregate without sending all CRM rows."""
    if lookup is None:
        return context
    data = _context(context)
    # An explicit empty list means this ERP was not present in the complete
    # browser-side index, rather than merely missing from a Top-N summary.
    data["stationIndex"] = lookup[:3]
    return json.dumps(data, ensure_ascii=False)

def _province_stats(data: dict[str, Any], province: str | None) -> tuple[str, dict[str, Any]]:
    requested = str(province or data.get("province", "全部省区")).strip()
    stats = data.get("provinceStats", {})
    if requested == "全部省区" or not stats:
        return requested, data
    key = next((k for k in stats if k == requested or k in requested or requested in k), requested)
    return key, stats.get(key, {})


def problem_type_ranking(context: str, province: str | None = None, metric: str = "拜访条数", sort: str = "desc", date_range: str | None = None) -> dict[str, Any]:
    data = _context(context)
    selected_province, province_stats = _province_stats(data, province)
    counts = province_stats.get("issueTypeCounts", {})
    ranking = [{"issue_type": k, "visits": int(v)} for k, v in sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))]
    return {"tool": "problem_type_ranking", "province": selected_province, "metric": metric or "拜访条数", "sort": sort or "desc", "date_range": date_range, "ranking": ranking}


def station_summary(context: str, province: str | None = None, date: str | None = None, top_n: int = 10) -> dict[str, Any]:
    data = _context(context)
    limit = max(1, min(int(top_n or 10), 50))
    if data.get("stationDateRanking"):
        return {"tool":"station_summary", "province":province or data.get("province", "全部省区"), "date":date or data.get("queryDate"), "issue_type":data.get("queryIssueType"), "top_n":limit, "stations":data["stationDateRanking"][:limit]}
    selected_province, stats = _province_stats(data, province)
    return {"tool": "station_summary", "province": selected_province, "top_n":limit, "stations": stats.get("topStations", [])[:limit]}

def station_lookup(context: str, erp: str) -> dict[str, Any]:
    data = _context(context)
    key = str(erp or "").strip().lower()
    candidates = data.get("stationIndex")
    if isinstance(candidates, list):
        station = next((item for item in candidates if str(item.get("erp", "")).strip().lower() == key or key in str(item.get("erp", "")).strip().lower()), None)
    else:
        station = next((item for item in data.get("topStations", []) if str(item.get("erp", "")).strip().lower() == key), None)
    return {"tool":"station_lookup", "erp":erp, "found":station is not None, "station":station, "note":"仅返回当前上传文件中 CRM 已识别质检问题的汇总。"}

def station_issue_date_count(context: str) -> dict[str, Any]:
    """Count one station's issue records for one exact date."""
    data = _context(context)
    detail = data.get("queryDetail") or {}
    return {"tool":"station_issue_date_count", "erp":detail.get("erp"), "date":detail.get("date"), "issue_type":detail.get("issue_type"), "visits":int(detail.get("visits", 0) or 0), "matched":bool(detail.get("matched")), "note":"按当前上传文件逐条记录、拜访日期和 CRM 质检问题类型确定性统计。"}


def extract_erp(question: str) -> str | None:
    """Extract a likely ERP account from a direct lookup question.

    A standalone latin/digit token such as ``shizhuangzhuang`` is treated as
    an ERP query.  Chinese-only questions must still be routed by intent.
    """
    matches = re.findall(r"(?<![A-Za-z0-9_.-])([A-Za-z][A-Za-z0-9_.-]{2,})(?![A-Za-z0-9_.-])", question or "")
    ignored = {"erp", "crm", "excel", "api", "json", "fastapi"}
    return next((value for value in matches if value.lower() not in ignored), None)

def has_date_condition(question: str) -> bool:
    """Recognize common natural-language date forms without hard-coding one spelling."""
    q = str(question or "")
    return bool(re.search(r"(?:\d{4}\s*年\s*)?\d{1,2}\s*(?:月\s*\d{1,2}\s*日|[-/.]\s*\d{1,2})(?:\s*日)?", q) or re.search(r"今天|当天|那天", q))


def data_quality_check(context: str) -> dict[str, Any]:
    data = _context(context)
    present = set(data.get("columns", [])); missing = sorted({"质检问题类型"} - present) if present else []
    return {"tool": "data_quality_check", "rows": int(data.get("rows", 0) or 0), "province": data.get("province", "全部省区"), "missing_columns": missing, "has_summary": bool(data.get("topStations") or data.get("issueTypeCounts")), "valid": not missing}

def consecutive_problem_days(context: str) -> dict[str, Any]:
    data = _context(context); result = []
    for station in data.get("topStations", []):
        days = sorted({str(x)[:10] for x in station.get("problemDates", station.get("datesList", [])) if str(x)[:10]})
        longest = current = 0; previous = None
        for value in days:
            try: current = current + 1 if previous and date.fromisoformat(value) == previous + timedelta(days=1) else 1
            except ValueError: current = 1
            longest = max(longest, current)
            try: previous = date.fromisoformat(value)
            except ValueError: previous = None
        if longest > 1: result.append({"erp": station.get("erp"), "province": station.get("province"), "consecutive_days": longest})
    return {"tool": "consecutive_problem_days", "stations": sorted(result, key=lambda x: -x["consecutive_days"])}

def station_multi_problem_types(context: str) -> dict[str, Any]:
    data = _context(context)
    return {"tool": "station_multi_problem_types", "stations": [{"erp": s.get("erp"), "province": s.get("province"), "problem_types": s.get("types", [])} for s in data.get("topStations", []) if len(set(s.get("types", []))) >= 2]}

def repeated_customers(context: str) -> dict[str, Any]:
    data = _context(context); customers = data.get("repeatedCustomers", [])
    return {"tool": "repeated_customers", "customers": customers if isinstance(customers, list) else []}

def explain_score(context: str, station_erp: str | None = None) -> dict[str, Any]:
    data = _context(context); station = next((x for x in data.get("topStations", []) if x.get("erp") == station_erp), None)
    return {"tool": "explain_score", "erp": station_erp, "station": station, "note": "重点排序沿用页面/通报口径；本工具只解释已提供的结果。"}

def generate_bulletin_summary(context: str, province: str | None = None) -> dict[str, Any]:
    data = _context(context)
    selected_province, scoped = _province_stats(data, province)
    stations = scoped.get("topStations", []) if isinstance(scoped.get("topStations", []), list) else []
    ranking = problem_type_ranking(data, selected_province)["ranking"]
    rows = int(data.get("rows", 0) or 0) if not province and not data.get("provinceStats") else (sum(int(s.get("visits", 0) or 0) for s in stations) if selected_province != "全部省区" else int(data.get("rows", 0) or 0))
    return {"tool":"generate_bulletin_summary", "province":selected_province, "rows":rows, "top_stations":stations[:10], "problem_type_ranking":ranking[:10], "disclaimer":"仅汇总 CRM 已有质检问题类型，不新增虚假拜访判断。"}

def validate_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    valid = isinstance(result, dict) and isinstance(result.get("tool"), str)
    return {"valid": valid, "errors": [] if valid else ["工具结果缺少 tool 字段"], "tool": result.get("tool") if isinstance(result, dict) else None}

def validate_tool_result_against_plan(tool: str, plan: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Validate that a browser result belongs to the exact planned tool call."""
    errors: list[str] = []
    if not isinstance(result, dict) or result.get("tool") != tool:
        errors.append("工具名与查询计划不一致")
    if tool == "spreadsheet_query":
        if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
            errors.append("表格查询结果缺少 rows")
        scope = result.get("scope") if isinstance(result, dict) else None
        if not isinstance(scope, dict):
            errors.append("表格查询结果缺少 scope")
        else:
            for key in ("filters", "group_by", "metric", "order", "limit"):
                if scope.get(key) != plan.get(key):
                    errors.append(f"表格查询字段不一致: {key}")
    return {"valid": not errors, "errors": errors, "tool": tool}

TOOL_DEFINITIONS = [
    {"type":"function","function":{"name":"problem_type_ranking","description":"先识别省区、指标、排序和日期范围，再统计质检问题类型","parameters":{"type":"object","properties":{"province":{"type":"string"},"metric":{"type":"string","enum":["拜访条数"]},"sort":{"type":"string","enum":["asc","desc"]},"date_range":{"type":"string"}},"additionalProperties":False}}},
    {"type":"function","function":{"name":"station_summary","description":"按省区、日期和质检问题类型返回站长排名；用户问谁、哪个、前几名或 Top N 时使用","parameters":{"type":"object","properties":{"province":{"type":"string"},"date":{"type":"string"},"top_n":{"type":"integer","minimum":1,"maximum":50}},"additionalProperties":False}}},
    {"type":"function","function":{"name":"station_lookup","description":"按站长ERP查询当前上传文件中的站长情况","parameters":{"type":"object","properties":{"erp":{"type":"string","description":"站长ERP账号"}},"required":["erp"],"additionalProperties":False}}},
    {"type":"function","function":{"name":"station_issue_date_count","description":"按站长ERP、具体日期和质检问题类型统计准确次数","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
    {"type":"function","function":{"name":"consecutive_problem_days","description":"按去重后的自然日计算连续问题天数","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
    {"type":"function","function":{"name":"station_multi_problem_types","description":"找出涉及至少两类质检问题的站长","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
    {"type":"function","function":{"name":"repeated_customers","description":"返回已由本地统计识别的重复客户","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
    {"type":"function","function":{"name":"data_quality_check","description":"检查上传摘要是否满足分析条件","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
    {"type":"function","function":{"name":"explain_score","description":"解释已生成的重点站长排序，不重新计算评分","parameters":{"type":"object","properties":{"station_erp":{"type":"string"}},"additionalProperties":False}}},
    {"type":"function","function":{"name":"generate_bulletin_summary","description":"生成指定省区的确定性通报摘要","parameters":{"type":"object","properties":{"province":{"type":"string"}},"additionalProperties":False}}},
]

TOOL_FUNCTIONS = {name: globals()[name] for name in ("problem_type_ranking", "station_summary", "station_lookup", "station_issue_date_count", "consecutive_problem_days", "station_multi_problem_types", "repeated_customers", "data_quality_check", "explain_score", "generate_bulletin_summary")}

def execute_tool(name: str, arguments: dict[str, Any], context: str | dict[str, Any]) -> dict[str, Any]:
    """Execute only a registered function; model arguments cannot supply data."""
    if name not in TOOL_FUNCTIONS:
        return {"tool": name, "error": "未注册的工具"}
    allowed = {"province", "station_erp", "erp"}
    if name == "problem_type_ranking": allowed |= {"metric", "sort", "date_range"}
    if name == "station_summary": allowed |= {"date", "top_n"}
    safe_args = {k: v for k, v in arguments.items() if k in allowed}
    result = TOOL_FUNCTIONS[name](context, **safe_args)
    result["validation"] = validate_tool_result(result)
    return result


def choose_tool(question: str, context: str) -> dict[str, Any]:
    if re.search(r"字段|导出|CRM|规则|评分|口径|通报|怎么判定|上传", question, re.I):
        return {"tool": "knowledge_retrieval", "result": None}
    erp = extract_erp(question)
    if erp and re.search(r"多少次|几次|次数|数量", question) and has_date_condition(question): result = station_issue_date_count(context)
    elif erp or re.search(r"erp|站长账号|站长情况|这个站长", question, re.I): result = station_lookup(context, erp or "")
    elif re.search(r"摘要|汇报|总结", question): result = generate_bulletin_summary(context)
    elif re.search(r"连续|多天", question): result = consecutive_problem_days(context)
    elif re.search(r"多类|两类|同时", question): result = station_multi_problem_types(context)
    elif re.search(r"重复.*客户|客户.*重复", question): result = repeated_customers(context)
    elif re.search(r"为什么.*排|评分", question): result = explain_score(context)
    # When the user asks for people/stations, keep the subject of the query
    # ahead of ranking words such as “最多”.  Otherwise a request like
    # “找出虚假的站长” or “哪些站长问题最多” can be misread as a ranking of
    # the issue type named “疑似虚假上报异常”.
    elif (re.search(r"站长|谁|哪位|哪个|前\s*[一二三四五六七八九十\d]+|top\s*\d+", question, re.I)) and not re.search(r"问题类型|哪类问题|什么问题", question): result = station_summary(context)
    elif re.search(r"问题类型|哪类问题|拍照|录入内容|最多", question): result = problem_type_ranking(context)
    elif re.search(r"完整|缺少|字段|数据", question): result = data_quality_check(context)
    else: return {"tool": "fallback", "result": None}
    return {"tool": result["tool"], "result": result, "validation": validate_tool_result(result)}
