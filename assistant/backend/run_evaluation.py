"""Run the de-identified planner evaluation set against a local backend."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .evaluation import score_plan_result


CASES_PATH = Path(__file__).with_name("eval_cases.json")
SCHEMA_CONTEXT = {
    "date_min": "2026-10-08",
    "date_max": "2026-10-13",
    "provinces": ["广东省区", "浙江省区", "河北省区", "上海区"],
    "issue_types": ["录入内容重复", "重复拜访", "拍照不规范", "疑似虚假上报异常"],
    "fields": ["省区", "站长ERP", "拜访日期", "客户", "问题类型"],
}


def _post_plan(base_url: str, question: str) -> dict:
    body = json.dumps({
        "question": question,
        "schema_context": SCHEMA_CONTEXT,
        "session_id": uuid.uuid4().hex,
    }, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/api/plan",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="评测自然语言查询规划")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条；0 表示全部")
    args = parser.parse_args()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if args.limit > 0:
        cases = cases[:args.limit]

    passed = 0
    for case in cases:
        try:
            actual = _post_plan(args.base_url, case["question"])
            score = score_plan_result(actual, case)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            print(f"FAIL {case['id']}: request_error={type(exc).__name__}")
            continue
        if score["passed"]:
            passed += 1
            print(f"PASS {case['id']}")
        else:
            failed = ",".join(score["failed_checks"])
            print(f"FAIL {case['id']}: {failed}; actual={json.dumps(actual, ensure_ascii=False)}")

    total = len(cases)
    print(f"RESULT {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
