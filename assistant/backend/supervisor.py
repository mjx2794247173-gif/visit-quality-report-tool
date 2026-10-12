"""Small LangGraph supervisor used to make routing observable and testable.

The graph only decides the workflow branch. It never computes CRM statistics.
"""
from __future__ import annotations
from typing import Any, TypedDict

class SupervisorState(TypedDict, total=False):
    question: str
    branch: str

def _route(state: SupervisorState) -> SupervisorState:
    import re
    q = state["question"]
    if re.search(r"字段|导出|CRM|规则|评分|口径|通报|上传", q, re.I): branch = "knowledge_qa"
    elif re.search(r"哪个|哪位|谁|最多|连续|重复|问题|站长|客户", q): branch = "deterministic_analysis"
    else: branch = "fallback"
    return {**state, "branch": branch}

try:
    from langgraph.graph import END, StateGraph
    _graph = StateGraph(SupervisorState)
    _graph.add_node("supervisor", _route)
    _graph.set_entry_point("supervisor")
    _graph.add_edge("supervisor", END)
    GRAPH = _graph.compile()
    LANGGRAPH_AVAILABLE = True
except ImportError:
    GRAPH = None
    LANGGRAPH_AVAILABLE = False
    LANGGRAPH_ERROR = "import_error"
except Exception:
    GRAPH = None
    LANGGRAPH_AVAILABLE = False
    LANGGRAPH_ERROR = "graph_build_error"

def supervise(question: str) -> dict[str, Any]:
    state = GRAPH.invoke({"question": question}) if GRAPH else _route({"question": question})
    return {"branch": state["branch"], "langgraph": LANGGRAPH_AVAILABLE}
