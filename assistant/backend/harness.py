"""Small, deterministic guardrails around the probabilistic Agent.

This module intentionally contains policy decisions that must not be delegated
to the model.  It is the first Harness layer: reject unsafe interpretations
before routing or tool execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    route: str | None = None
    reason: str | None = None


# These questions ask the system to make a judgement that is outside the CRM
# fact model.  In particular, a photo or free-text feedback is not evidence of
# a fraudulent visit; only the CRM's quality issue type is.
UNSUPPORTED_JUDGEMENT_PATTERN = re.compile(
    r"(?:照片|图片|截图|拍摄内容|根据反馈|反馈内容|看图|看照片).{0,24}"
    r"(?:判断|认定|确定|识别|证明).{0,24}"
    r"(?:虚假|违规|造假|真实|不真实|异常拜访)|"
    r"(?:判断|认定|确定|识别|证明).{0,24}"
    r"(?:照片|图片|截图|反馈内容).{0,24}"
    r"(?:虚假|违规|造假|真实|不真实|异常拜访)",
    re.IGNORECASE,
)


def check_question_policy(question: str) -> PolicyDecision:
    """Apply hard safety boundaries before the Agent sees the request."""
    if UNSUPPORTED_JUDGEMENT_PATTERN.search(question.strip()):
        return PolicyDecision(
            allowed=False,
            route="out_of_scope",
            reason="不能查看照片或根据反馈内容自行判断虚假拜访；只能使用 CRM 已识别的质检问题类型。",
        )
    return PolicyDecision(allowed=True)

