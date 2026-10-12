"""Safe, read-only tools used by the assistant router.

These functions consume the browser's aggregated report context. They do not
read files, execute SQL, or decide whether a visit is fraudulent.
"""
from __future__ import annotations

import json
import re
from typing import Any


def _context(context: str) -> dict[str, Any]:
    try:
        value = json.loads(context or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def problem_type_ranking(context: str) -> dict[str, Any]:
    data = _context(context)
    counts = data.get("issueTypeCounts", {})
    return {"tool": "problem_type_ranking", "province": data.get("province", "全部省区"), "ranking": sorted(counts.items(), key=lambda item: item[1], reverse=True)}


def station_summary(context: str) -> dict[str, Any]:
    data = _context(context)
    return {"tool": "station_summary", "province": data.get("province", "全部省区"), "stations": data.get("topStations", [])}


def data_quality_check(context: str) -> dict[str, Any]:
    data = _context(context)
    return {"tool": "data_quality_check", "rows": data.get("rows", 0), "province": data.get("province", "全部省区"), "has_summary": bool(data.get("topStations") or data.get("issueTypeCounts"))}


def choose_tool(question: str, context: str) -> dict[str, Any]:
    if re.search(r"字段|导出|CRM|规则|评分|口径|通报|怎么判定|上传", question, re.I):
        return {"tool": "knowledge_retrieval", "result": None}
    if re.search(r"问题类型|哪类问题|拍照|录入内容|最多", question):
        return {"tool": "problem_type_ranking", "result": problem_type_ranking(context)}
    if re.search(r"站长|连续|多天|谁|哪位", question):
        return {"tool": "station_summary", "result": station_summary(context)}
    if re.search(r"完整|缺少|字段|数据", question):
        return {"tool": "data_quality_check", "result": data_quality_check(context)}
    return {"tool": "fallback", "result": None}
