"""Offline retrieval-K evaluation for the stable knowledge base.

This evaluates evidence coverage, not final LLM answer quality.  It is
deliberately deterministic when run with RAG_BACKEND=keyword, so K comparisons
are repeatable without making model calls.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from assistant.backend.main import retrieve  # type: ignore
else:
    from .main import retrieve


CASES = [
    {
        "id": "scoring_rule",
        "question": "重点站长评分怎么算？",
        "required_facts": ["虚假拜访", "问题类型", "持续", "客户数"],
    },
    {
        "id": "export_fields",
        "question": "CRM要导出哪些字段才能分析？",
        "required_facts": ["拜访编码", "客户编码", "拜访人ERP", "实际拜访时间", "质检问题类型"],
    },
    {
        "id": "statistics_scope",
        "question": "反馈内容无意义是否参与统计？",
        "required_facts": ["反馈内容无意义", "不参与", "统计"],
    },
    {
        "id": "bulletin_rule",
        "question": "每个省区通报选几名重点站长？",
        "required_facts": ["每个省区", "前三"],
    },
]


def evaluate(k_values: list[int]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for k in k_values:
        for case in CASES:
            started = time.perf_counter()
            sources = retrieve(case["question"], limit=k)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            evidence = "\n".join(item.get("text", "") for item in sources).lower()
            facts = [str(fact).lower() for fact in case["required_facts"]]
            hits = sum(fact in evidence for fact in facts)
            rows.append({
                "k": k,
                "case_id": case["id"],
                "source_count": len(sources),
                "fact_hits": hits,
                "fact_total": len(facts),
                "evidence_coverage": round(hits / len(facts), 4) if facts else 1.0,
                "context_chars": sum(len(item.get("text", "")) for item in sources),
                "elapsed_ms": elapsed_ms,
            })
    return rows


def summarize(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for k in sorted({int(row["k"]) for row in rows}):
        group = [row for row in rows if int(row["k"]) == k]
        result.append({
            "k": k,
            "case_count": len(group),
            "average_evidence_coverage": round(sum(float(row["evidence_coverage"]) for row in group) / len(group), 4),
            "all_facts_covered": sum(float(row["evidence_coverage"]) == 1.0 for row in group),
            "average_context_chars": round(sum(int(row["context_chars"]) for row in group) / len(group), 1),
            "average_elapsed_ms": round(sum(float(row["elapsed_ms"]) for row in group) / len(group), 1),
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare retrieval K values on knowledge evidence coverage")
    parser.add_argument("--k", nargs="+", type=int, default=[3, 6, 10, 20])
    parser.add_argument("--backend", choices=["keyword", "auto"], default="keyword")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()
    os.environ["RAG_BACKEND"] = args.backend
    rows = evaluate(args.k)
    print("SUMMARY")
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))
    if args.json:
        print("DETAILS")
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
