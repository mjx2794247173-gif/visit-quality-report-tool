"""Run a small de-identified multi-turn planner evaluation."""
from __future__ import annotations

import json
import uuid
from urllib.request import Request, urlopen

SCHEMA_CONTEXT = {
    "date_min": "2026-10-08", "date_max": "2026-10-13",
    "provinces": ["广东省区", "浙江省区", "河北省区", "上海区"],
    "issue_types": ["录入内容重复", "重复拜访", "拍照不规范", "疑似虚假上报异常"],
    "fields": ["省区", "站长ERP", "拜访日期", "客户", "问题类型"],
}

CASES = [
    {
        "id": "inherit_date_change_province",
        "turns": [
            ("10月12日广东省区问题最多的前5名站长是谁？", {"tool": "spreadsheet_query", "filters": {"province": "广东省区", "date_from": "2026-10-12", "date_to": "2026-10-12"}}),
            ("那浙江呢？", {"tool": "spreadsheet_query", "filters": {"province": "浙江省区", "date_from": "2026-10-12", "date_to": "2026-10-12"}}),
            ("改成10月11日。", {"tool": "spreadsheet_query", "filters": {"province": "浙江省区", "date_from": "2026-10-11", "date_to": "2026-10-11"}}),
        ],
    },
    {
        "id": "publish_only_after_validated_answer",
        "turns": [
            ("10月12日广东省区问题最多的前5名站长是谁？", {"tool": "spreadsheet_query", "filters": {"province": "广东省区"}}),
            ("把上一条分析结果推送到飞书", {"tool": "feishu_publish_preview", "filters": {}}),
        ],
    },
]

def post_plan(base_url: str, session_id: str, question: str) -> dict:
    body = json.dumps({"question": question, "schema_context": SCHEMA_CONTEXT, "session_id": session_id}, ensure_ascii=False).encode()
    request = Request(f"{base_url.rstrip('/')}/api/plan", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())

def post_answer(base_url: str, session_id: str, question: str, planned: dict) -> None:
    plan = planned.get("plan", {})
    result = {"tool": planned.get("tool")}
    if planned.get("tool") == "spreadsheet_query":
        result.update({
            "scope": plan,
            "filtered_rows": 0,
            "total_rows": 0,
            "rows": [],
            "facets": {"issue_types": [], "stations": [], "station_province_counts": []},
            "data_source": "脱敏评测数据",
        })
    body = json.dumps({"question": question, "plan": plan, "tool_result": result, "session_id": session_id, "trace_id": planned.get("trace_id"), "workflow_id": planned.get("workflow_id"), "plan_signature": planned.get("plan_signature")}, ensure_ascii=False).encode()
    request = Request(f"{base_url.rstrip('/')}/api/answer", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=60):
        pass

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    args = parser.parse_args()
    failures = 0
    for case in CASES:
        session_id = uuid.uuid4().hex
        for index, (question, expected) in enumerate(case["turns"], start=1):
            actual = post_plan(args.base_url, session_id, question)
            filters = actual.get("plan", {}).get("filters", {})
            expected_filters = expected.get("filters", {})
            passed = actual.get("tool") == expected["tool"] and all(filters.get(key) == value for key, value in expected_filters.items())
            print(("PASS" if passed else "FAIL"), case["id"], f"turn={index}", f"tool={actual.get('tool')}", json.dumps(filters, ensure_ascii=False))
            failures += not passed
            if passed and actual.get("tool") == "spreadsheet_query":
                post_answer(args.base_url, session_id, question, actual)
    return int(bool(failures))

if __name__ == "__main__":
    raise SystemExit(main())
