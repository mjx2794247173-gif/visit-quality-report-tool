from assistant.backend.main import clean_generated_answer


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
