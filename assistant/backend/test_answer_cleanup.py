from datetime import datetime

from assistant.backend.main import clean_generated_answer, current_calendar_context, general_chat_history


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
