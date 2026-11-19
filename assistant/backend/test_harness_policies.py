from .harness import check_question_policy


def test_photo_fraud_judgement_is_blocked_before_agent_routing():
    decision = check_question_policy("请根据拜访照片判断这个站长是不是虚假拜访")
    assert decision.allowed is False
    assert decision.route == "out_of_scope"


def test_feedback_fraud_judgement_is_blocked():
    decision = check_question_policy("根据反馈内容认定这次是不是造假")
    assert decision.allowed is False


def test_crm_issue_query_remains_allowed():
    decision = check_question_policy("统计质检问题类型为疑似虚假拜访的站长")
    assert decision.allowed is True
