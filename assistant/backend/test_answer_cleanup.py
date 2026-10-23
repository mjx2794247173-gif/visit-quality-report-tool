from datetime import datetime

from assistant.backend.main import clean_generated_answer, current_calendar_context, deterministic_spreadsheet_answer, general_chat_history, spreadsheet_answer_grounding_errors


def test_removes_unsolicited_trailing_explanation() -> None:
    answer = (
        "重复拜访次数最多的客户如下：\n"
        "| 客户编码 | 次数 | 省区 |\n"
        "| C001 | 3 | 广东省区 |\n\n"
        "需要说明的是，以上只是 CRM 已识别的问题记录统计。如需进一步查看，可以继续查询。"
    )

    cleaned = clean_generated_answer(answer)

    assert "C001" in cleaned
    assert "需要说明的是" not in cleaned
    assert "如需进一步查看" not in cleaned


def test_keeps_requested_result_paragraphs() -> None:
    answer = "广东省区共 590 条。\n\n上海区共 363 条。"

    assert clean_generated_answer(answer) == answer


def test_calendar_context_calculates_current_week_deterministically() -> None:
    context = current_calendar_context(datetime(2026, 10, 23, 12, 0))

    assert context == {
        "today": "2026-10-23",
        "current_week_monday": "2026-10-19",
        "current_week_sunday": "2026-10-25",
    }


def test_general_chat_history_excludes_business_answers() -> None:
    history = [
        {
            "question": "分析本周数据",
            "result": {"tool": "spreadsheet_query"},
            "answer": "本周从10月15日开始。",
        },
        {
            "question": "你是谁？",
            "result": {"tool": "general_chat"},
            "answer": "我是拜访质量分析助手。",
        },
    ]

    assert general_chat_history(history) == [
        {"question": "你是谁？", "answer": "我是拜访质量分析助手。"}
    ]


def _spreadsheet_result() -> dict:
    return {
        "filtered_rows": 12,
        "total_rows": 20,
        "rows": [{"label": "录入不规范", "value": 4}],
        "facets": {
            "issue_types": [{
                "label": "录入不规范",
                "value": 4,
                "dominant_province": "江苏省区",
                "dominant_province_value": 3,
                "province_ranking": [
                    {"province": "江苏省区", "value": 3},
                    {"province": "湖北省区", "value": 1},
                ],
            }],
            "stations": [{"label": "demo001", "value": 2, "province": "江苏省区"}],
            "station_province_counts": [{"province": "江苏省区", "value": 1}],
        },
    }


def test_spreadsheet_grounding_rejects_unreturned_number() -> None:
    errors = spreadsheet_answer_grounding_errors("录入不规范共有54条。", _spreadsheet_result())

    assert "数字 54 没有当前工具结果依据" in errors
    assert "录入不规范 的数量应为 4，不是 54" in errors


def test_spreadsheet_grounding_rejects_wrong_concentration_province() -> None:
    errors = spreadsheet_answer_grounding_errors("录入不规范4条，集中在湖北省区。", _spreadsheet_result())

    assert "录入不规范 的集中省区应为 江苏省区，不是 湖北省区" in errors


def test_spreadsheet_grounding_rejects_number_attached_to_wrong_entity() -> None:
    result = _spreadsheet_result()
    result["facets"]["issue_types"].append({
        "label": "拍照不规范", "value": 12,
        "dominant_province": "湖北省区", "dominant_province_value": 12,
        "province_ranking": [{"province": "湖北省区", "value": 12}],
    })

    errors = spreadsheet_answer_grounding_errors("录入不规范12条，拍照不规范4条。", result)

    assert "录入不规范 的数量应为 4，不是 12" in errors
    assert "拍照不规范 的数量应为 12，不是 4" in errors


def test_spreadsheet_grounding_rejects_wrong_station_count() -> None:
    errors = spreadsheet_answer_grounding_errors("demo001有4条问题。", _spreadsheet_result())

    assert "站长 demo001 的数量应为 2，不是 4" in errors


def test_deterministic_report_uses_only_verified_facets() -> None:
    answer = deterministic_spreadsheet_answer("生成完整报告", {}, _spreadsheet_result())

    assert "12 条" in answer
    assert "录入不规范 4 条" in answer
    assert "江苏省区（3 条）" in answer
    assert "demo001 2 条" in answer
    assert "54" not in answer
