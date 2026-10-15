"""Local FastAPI backend for the quality bulletin assistant.

The browser keeps CRM rows local.  This service receives only the question and
small, already-aggregated context, then routes the request to knowledge
retrieval and DeepSeek.  It never decides whether a visit is fraudulent.
"""
from __future__ import annotations

import json
import os
import re
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from langgraph.graph import END, StateGraph
from .tools import attach_erp_lookup, choose_tool, TOOL_DEFINITIONS, execute_tool, extract_erp, validate_tool_result
from .supervisor import supervise
from .feishu import get_feishu_status, send_feishu_message

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "server" / ".env", override=True)
KNOWLEDGE = ROOT / "knowledge"
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
BUILD_VERSION = "2026.10.14-feishu-mcp-v1"

app = FastAPI(title="虚假拜访问答助手", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
sessions: dict[str, dict[str, Any]] = {}
logger = logging.getLogger("visit_quality_assistant")
AUDIT_LOG = ROOT / "server" / "assistant_calls.jsonl"
_rag_collection = None
_rag_model = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    context: str = Field(default="", max_length=500000)
    erp_lookup: list[dict[str, Any]] | None = None
    session_id: str = Field(default="default", max_length=100)

class PlanRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    schema_context: dict[str, Any] = Field(default_factory=dict)
    session_id: str = Field(default="browser-session", max_length=100)

class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    plan: dict[str, Any]
    tool_result: dict[str, Any]
    session_id: str = Field(default="browser-session", max_length=100)


class FeishuSendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    confirmed: bool = False
    session_id: str = Field(default="browser-session", max_length=100)


class AgentDecision(BaseModel):
    """Validated output contract for the LangGraph supervisor."""

    model_config = ConfigDict(extra="forbid")
    agent: Literal["data_agent", "knowledge_agent", "quality_agent", "publishing_agent"]


class SpreadsheetFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    province: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    station_erp: str | None = None
    issue_type: str | None = None


class SpreadsheetPlan(BaseModel):
    """Validated query contract produced by the data specialist Agent."""

    model_config = ConfigDict(extra="forbid")
    filters: SpreadsheetFilters = Field(default_factory=SpreadsheetFilters)
    group_by: Literal["station_erp", "issue_type", "province", "date", "customer", "none"]
    metric: Literal[
        "visit_count",
        "distinct_visit_count",
        "distinct_issue_type_count",
        "distinct_date_count",
        "distinct_customer_count",
    ]
    order: Literal["desc", "asc"]
    limit: int = Field(ge=1, le=50)


class KnowledgePlan(BaseModel):
    """Validated retrieval query produced by the knowledge specialist Agent."""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


class RetrievalAssessment(BaseModel):
    """Whether retrieved knowledge is enough to answer without guessing."""

    model_config = ConfigDict(extra="forbid")
    is_sufficient: bool
    missing_information: str = Field(max_length=500)


class RetrievalRewrite(BaseModel):
    """A single supplemental search query produced after insufficient retrieval."""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


class EmptyToolPlan(BaseModel):
    """Contract for specialist tools that intentionally accept no arguments."""

    model_config = ConfigDict(extra="forbid")


def chunks(text: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for file in sorted(KNOWLEDGE.glob("*.md")):
        content = file.read_text(encoding="utf-8")
        parts = re.split(r"\n(?=##?\s)", content)
        result.extend({"source": file.name, "text": p.strip()} for p in parts if p.strip())
    return result


def retrieve(question: str, limit: int = 6) -> list[dict[str, str]]:
    """Use Chroma + Chinese embeddings when installed; otherwise keyword fallback."""
    global _rag_collection, _rag_model
    try:
        if os.getenv("RAG_BACKEND", "auto").lower() != "keyword":
            import chromadb
            from sentence_transformers import SentenceTransformer
            if _rag_collection is None:
                _rag_model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"))
                client = chromadb.PersistentClient(path=str(ROOT / "rag" / "chroma_db"))
                _rag_collection = client.get_or_create_collection("quality_bulletin_knowledge", metadata={"hnsw:space":"cosine"})
                if _rag_collection.count() == 0:
                    docs = chunks(""); texts = [x["text"] for x in docs]
                    if texts: _rag_collection.add(ids=[f"doc-{i}" for i in range(len(texts))], documents=texts, metadatas=[{"source":x["source"]} for x in docs], embeddings=_rag_model.encode(texts, normalize_embeddings=True).tolist())
            if _rag_collection.count():
                result = _rag_collection.query(query_embeddings=_rag_model.encode([question], normalize_embeddings=True).tolist(), n_results=min(limit, _rag_collection.count()))
                return [{"source":m.get("source","") if m else "", "text":t} for t,m in zip(result.get("documents",[[]])[0], result.get("metadatas",[[]])[0])]
    except Exception as exc:
        logger.warning("rag_vector_fallback error=%s", type(exc).__name__)
    terms = re.findall(r"[\u4e00-\u9fff]{2}|[a-zA-Z0-9_]{2,}", question.lower())
    scored = []
    for item in chunks(question):
        score = sum(item["text"].lower().count(term) for term in set(terms))
        if score:
            scored.append((score, item))
    return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]


def audit(event: dict[str, Any]) -> None:
    """Write metadata only; never persist CRM rows, customer names, or context."""
    safe = {"time": datetime.now(timezone.utc).isoformat(), **event}
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("audit_log_unavailable")


def upstream_error(response: httpx.Response, fallback: str) -> str:
    """Return a safe message even when the model gateway responds with HTML/text."""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("error")
            if isinstance(detail, dict) and detail.get("message"):
                return str(detail["message"])
            if payload.get("detail"):
                return str(payload["detail"])
    except (ValueError, TypeError):
        pass
    return fallback

def infer_province(question: str, context: str) -> str | None:
    """Fill an omitted province argument from explicit user text, never from model guess."""
    try:
        data = json.loads(context or "{}")
        keys = list((data.get("provinceStats") or {}).keys())
        return next((key for key in keys if key in question or key.replace("省区", "") in question), None)
    except (TypeError, json.JSONDecodeError):
        return None


def route(question: str) -> str:
    return supervise(question)["branch"]


SYSTEM = (
    "你是省区虚假拜访质量分析助手。只能解释 CRM 已识别的质检问题，"
    "不能自行判断虚假、查看照片或编造统计结果。数据问题优先相信调用方提供的确定性分析结果；"
    "规则问题只依据提供的业务资料。回答前先在内部理解用户意图、范围和口径，再给结论；不要展示思维过程、原始 JSON、内部结构化摘要、工具参数或内部提示。默认使用自然、简洁的中文段落，不要滥用 Markdown、模板化标题或机器人腔。"
)

KNOWLEDGE_TOOL = {"type":"function","function":{"name":"knowledge_retrieval","description":"检索评分规则、字段说明、CRM导出要求、统计口径、通报规则、FAQ和安全边界","parameters":{"type":"object","properties":{"query":{"type":"string","description":"需要检索的业务知识问题"}},"required":["query"],"additionalProperties":False}}}

RETRIEVAL_ASSESSMENT_TOOL = {"type":"function","function":{"name":"submit_retrieval_assessment","description":"判断检索资料是否足以回答用户问题，不得使用模型自身知识补全。","parameters":{"type":"object","properties":{"is_sufficient":{"type":"boolean"},"missing_information":{"type":"string","description":"资料不足时说明缺少什么；资料充分时为空字符串","maxLength":500}},"required":["is_sufficient","missing_information"],"additionalProperties":False}}}

RETRIEVAL_REWRITE_TOOL = {"type":"function","function":{"name":"submit_rewritten_query","description":"根据用户原问题和缺失信息生成一次更适合知识库检索的查询，不回答问题。","parameters":{"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":500}},"required":["query"],"additionalProperties":False}}}

SPREADSHEET_QUERY_TOOL = {"type":"function","function":{"name":"spreadsheet_query","description":"对浏览器当前上传的 CRM Excel 执行通用筛选、分组、计数、排序和 Top N 查询。用户问站长、问题类型、省区、日期、客户或次数时使用。‘虚假/违规’不是具体问题类型，除非用户明确说出 schema 中存在的质检问题类型。","parameters":{"type":"object","properties":{"filters":{"type":"object","properties":{"province":{"type":["string","null"]},"date_from":{"type":["string","null"]},"date_to":{"type":["string","null"]},"station_erp":{"type":["string","null"]},"issue_type":{"type":["string","null"]}},"additionalProperties":False},"group_by":{"type":"string","enum":["station_erp","issue_type","province","date","customer","none"]},"metric":{"type":"string","enum":["visit_count","distinct_visit_count","distinct_issue_type_count","distinct_date_count","distinct_customer_count"]},"order":{"type":"string","enum":["desc","asc"]},"limit":{"type":"integer","minimum":1,"maximum":50}},"required":["filters","group_by","metric","order","limit"],"additionalProperties":False}}}

DATA_QUALITY_TOOL = {"type":"function","function":{"name":"data_quality_check","description":"检查当前上传 Excel 的必需字段、空值、日期范围和可分析记录数。用户问文件是否完整、字段是否缺失、为什么无法分析时使用。","parameters":{"type":"object","properties":{},"additionalProperties":False}}}

FEISHU_PREVIEW_TOOL = {"type":"function","function":{"name":"feishu_publish_preview","description":"为最近一次回答生成飞书发布预览。用户明确说发送、推送、发到飞书时使用；此工具只准备内容，页面仍需用户确认。","parameters":{"type":"object","properties":{},"additionalProperties":False}}}

PLANNER_TOOLS = [SPREADSHEET_QUERY_TOOL, KNOWLEDGE_TOOL, DATA_QUALITY_TOOL, FEISHU_PREVIEW_TOOL]

DELEGATE_AGENT_TOOL = {"type":"function","function":{"name":"delegate_to_agent","description":"根据用户意图把任务委派给一个专业 Agent。","parameters":{"type":"object","properties":{"agent":{"type":"string","enum":["data_agent","knowledge_agent","quality_agent","publishing_agent"]}},"required":["agent"],"additionalProperties":False}}}


class MultiAgentState(TypedDict, total=False):
    question: str
    schema_context: dict[str, Any]
    recent: list[dict[str, Any]]
    agent: str
    tool: str
    plan: dict[str, Any]


async def _function_call(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Ask DeepSeek for exactly one tool call and return its validated envelope."""
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={"model": MODEL, "messages": messages, "tools": tools, "tool_choice": "required", "thinking": {"type": "disabled"}, "stream": False, "max_tokens": 600},
            )
    except httpx.HTTPError as exc:
        raise RuntimeError("模型服务暂时不可用，请稍后重试") from exc
    if response.status_code >= 400:
        raise RuntimeError(upstream_error(response, "模型工具调用失败，请稍后重试"))
    try:
        call = (response.json()["choices"][0]["message"].get("tool_calls") or [])[0]
        name = str(call["function"]["name"])
        arguments = json.loads(call["function"].get("arguments") or "{}")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise RuntimeError("模型返回的工具调用格式异常，请重试") from exc
    return name, arguments if isinstance(arguments, dict) else {}


async def assess_retrieval_sufficiency(question: str, sources: list[dict[str, str]]) -> RetrievalAssessment:
    """Conservatively verify that retrieved documents cover the requested answer."""
    if not sources:
        return RetrievalAssessment(is_sufficient=False, missing_information="知识库未检索到相关资料")
    evidence = [
        {"source": item.get("source", ""), "text": item.get("text", "")[:1800]}
        for item in sources[:6]
    ]
    messages = [
        {"role":"system","content":"你是知识检索结果审查员。只判断给定资料是否覆盖用户问题所需的关键信息，不回答问题，不使用模型自身知识。只要资料不能直接支持可靠答案，就判定为不足并简要说明缺少什么。必须调用 submit_retrieval_assessment。"},
        {"role":"user","content":json.dumps({"question":question,"sources":evidence}, ensure_ascii=False)},
    ]
    _, raw_assessment = await _function_call(messages, [RETRIEVAL_ASSESSMENT_TOOL])
    try:
        return RetrievalAssessment.model_validate(raw_assessment)
    except Exception as exc:
        raise RuntimeError("知识资料充分性审查结果无效，请重试") from exc


async def rewrite_retrieval_query(question: str, original_query: str, missing_information: str) -> RetrievalRewrite:
    """Rewrite one failed retrieval query without inventing facts or broadening intent."""
    messages = [
        {"role":"system","content":"你是知识检索查询改写员。根据用户原问题、第一次检索词和缺失信息，生成一个更适合检索业务知识库的中文查询。保留用户原意和限定条件，不回答问题，不增加用户未提及的事实。必须调用 submit_rewritten_query。"},
        {"role":"user","content":json.dumps({"question":question,"original_query":original_query,"missing_information":missing_information}, ensure_ascii=False)},
    ]
    _, raw_rewrite = await _function_call(messages, [RETRIEVAL_REWRITE_TOOL])
    try:
        return RetrievalRewrite.model_validate(raw_rewrite)
    except Exception as exc:
        raise RuntimeError("知识检索词改写结果无效，请重试") from exc


def merge_retrieval_sources(*source_groups: list[dict[str, str]], limit: int = 10) -> list[dict[str, str]]:
    """Merge supplemental retrieval results while preserving order and removing duplicates."""
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for group in source_groups:
        for item in group:
            normalized = {"source":str(item.get("source", "")), "text":str(item.get("text", ""))[:1800]}
            key = (normalized["source"], normalized["text"])
            if key not in seen:
                seen.add(key)
                merged.append(normalized)
            if len(merged) >= limit:
                return merged
    return merged


async def supervisor_agent(state: MultiAgentState) -> MultiAgentState:
    messages = [
        {"role":"system","content":"你是 LangGraph Supervisor Agent，只负责把任务委派给一个专业 Agent：数据统计与ERP查询交给 data_agent；规则、口径、评分和CRM导出说明交给 knowledge_agent；文件字段、空值、上传失败和可分析性检查交给 quality_agent；发送、推送或飞书发布交给 publishing_agent。必须调用 delegate_to_agent。"},
        {"role":"user","content":f"最近对话：{json.dumps(state.get('recent', []),ensure_ascii=False)}\n用户问题：{state['question']}"},
    ]
    _, arguments = await _function_call(messages, [DELEGATE_AGENT_TOOL])
    try:
        decision = AgentDecision.model_validate(arguments)
    except Exception as exc:
        raise RuntimeError("Supervisor 返回了无效的 Agent 决策，请重试") from exc
    return {**state, "agent": decision.agent}


def _agent_messages(state: MultiAgentState, instruction: str) -> list[dict[str, Any]]:
    return [
        {"role":"system","content":SYSTEM + instruction},
        {"role":"user","content":f"最近对话：{json.dumps(state.get('recent', []),ensure_ascii=False)}\n可用数据结构：{json.dumps(state.get('schema_context', {}),ensure_ascii=False)}\n用户问题：{state['question']}"},
    ]


async def data_agent(state: MultiAgentState) -> MultiAgentState:
    instruction = "你是数据分析 Agent，只能调用 spreadsheet_query。识别省区、日期、ERP、问题类型、分组、指标、排序和 Top N。不得把‘虚假’或‘违规’擅自映射成某个具体问题类型；泛指虚假次数时 issue_type=null。"
    tool, raw_plan = await _function_call(_agent_messages(state, instruction), [SPREADSHEET_QUERY_TOOL])
    try:
        query_plan = SpreadsheetPlan.model_validate(raw_plan)
    except Exception as exc:
        raise RuntimeError("Data Agent 返回了无效的 Excel 查询计划，请重试") from exc
    plan = query_plan.model_dump()
    filters = plan["filters"]
    issue_type = filters["issue_type"]
    if issue_type and str(issue_type) not in state["question"]:
        filters["issue_type"] = None
    plan["filters"] = filters
    return {**state, "tool": tool, "plan": plan}


async def knowledge_agent(state: MultiAgentState) -> MultiAgentState:
    tool, raw_plan = await _function_call(_agent_messages(state, "你是知识问答 Agent，只能调用 knowledge_retrieval 检索业务规则、统计口径、评分和CRM导出说明，不得凭模型记忆编造规则。"), [KNOWLEDGE_TOOL])
    try:
        plan = KnowledgePlan.model_validate(raw_plan).model_dump()
    except Exception as exc:
        raise RuntimeError("Knowledge Agent 返回了无效的检索计划，请重试") from exc
    return {**state, "tool": tool, "plan": plan}


async def quality_agent(state: MultiAgentState) -> MultiAgentState:
    tool, raw_plan = await _function_call(_agent_messages(state, "你是数据质量 Agent，只能调用 data_quality_check 检查当前上传文件。"), [DATA_QUALITY_TOOL])
    try:
        plan = EmptyToolPlan.model_validate(raw_plan).model_dump()
    except Exception as exc:
        raise RuntimeError("Quality Agent 返回了无效的检查计划，请重试") from exc
    return {**state, "tool": tool, "plan": plan}


async def publishing_agent(state: MultiAgentState) -> MultiAgentState:
    tool, raw_plan = await _function_call(_agent_messages(state, "你是发布 Agent，只能调用 feishu_publish_preview 准备上一条已校验回答的发布预览，不得声称已经发送。"), [FEISHU_PREVIEW_TOOL])
    try:
        plan = EmptyToolPlan.model_validate(raw_plan).model_dump()
    except Exception as exc:
        raise RuntimeError("Publishing Agent 返回了无效的发布计划，请重试") from exc
    return {**state, "tool": tool, "plan": plan}


def _next_agent(state: MultiAgentState) -> str:
    return state["agent"]


_multi_agent_builder = StateGraph(MultiAgentState)
_multi_agent_builder.add_node("supervisor_agent", supervisor_agent)
_multi_agent_builder.add_node("data_agent", data_agent)
_multi_agent_builder.add_node("knowledge_agent", knowledge_agent)
_multi_agent_builder.add_node("quality_agent", quality_agent)
_multi_agent_builder.add_node("publishing_agent", publishing_agent)
_multi_agent_builder.set_entry_point("supervisor_agent")
_multi_agent_builder.add_conditional_edges("supervisor_agent", _next_agent, {
    "data_agent":"data_agent",
    "knowledge_agent":"knowledge_agent",
    "quality_agent":"quality_agent",
    "publishing_agent":"publishing_agent",
})
for _agent_node in ("data_agent", "knowledge_agent", "quality_agent", "publishing_agent"):
    _multi_agent_builder.add_edge(_agent_node, END)
MULTI_AGENT_GRAPH = _multi_agent_builder.compile()

@app.post("/api/plan")
async def plan_query(payload: PlanRequest) -> JSONResponse:
    if not API_KEY:
        return JSONResponse({"error":"后端尚未配置 DEEPSEEK_API_KEY"}, status_code=503)
    state = sessions.setdefault(payload.session_id, {"history": []})
    recent = state.get("history", [])[-4:]
    try:
        graph_result = await MULTI_AGENT_GRAPH.ainvoke({"question":payload.question,"schema_context":payload.schema_context,"recent":recent})
    except RuntimeError as exc:
        logger.exception("multi_agent_plan_failed")
        return JSONResponse({"error":str(exc)}, status_code=502)
    return JSONResponse({"agent":graph_result["agent"],"tool":graph_result["tool"],"plan":graph_result.get("plan",{})})

@app.post("/api/answer")
async def answer_query(payload: AnswerRequest) -> JSONResponse:
    result = payload.tool_result
    tool_name = str(result.get("tool") or "")
    if tool_name == "spreadsheet_query" and not isinstance(result.get("rows"), list):
        return JSONResponse({"error":"表格查询结果校验失败"}, status_code=422)
    if tool_name == "data_quality_check" and not isinstance(result.get("required_fields"), list):
        return JSONResponse({"error":"数据质量检查结果校验失败"}, status_code=422)
    if tool_name == "knowledge_retrieval":
        query = str(payload.plan.get("query") or payload.question)
        docs = retrieve(query)
        sources = merge_retrieval_sources(docs)
        rewritten_query = ""
        retrieval_attempts = 1
        try:
            assessment = await assess_retrieval_sufficiency(payload.question, sources)
            if not assessment.is_sufficient:
                rewrite = await rewrite_retrieval_query(payload.question, query, assessment.missing_information)
                rewritten_query = rewrite.query
                supplemental_docs = retrieve(rewritten_query)
                sources = merge_retrieval_sources(supplemental_docs, sources)
                retrieval_attempts = 2
                assessment = await assess_retrieval_sufficiency(payload.question, sources)
        except RuntimeError as exc:
            return JSONResponse({"error":str(exc)}, status_code=502)
        result = {"tool":"knowledge_retrieval","query":query,"rewritten_query":rewritten_query or None,"retrieval_attempts":retrieval_attempts,"sources":sources,"assessment":assessment.model_dump()}
        if not assessment.is_sufficient:
            detail = assessment.missing_information.strip() or "现有资料没有覆盖回答所需的关键信息"
            separator = "" if detail.endswith(("。", "！", "？", ".", "!", "?")) else "。"
            answer = f"当前知识库资料不足以可靠回答这个问题：{detail}{separator}为避免编造，我先不做推断。"
            state = sessions.setdefault(payload.session_id, {"history": []})
            state["history"] = (state.get("history",[]) + [{"question":payload.question,"plan":payload.plan,"result":{"tool":tool_name,"sufficient":False},"answer":answer}])[-6:]
            return JSONResponse({"answer":answer,"tool":tool_name,"tool_result":result,"validation":{"valid":True,"sufficient":False}})
    if tool_name == "feishu_publish_preview":
        content = str(result.get("content") or "").strip()
        if not content:
            return JSONResponse({"error":"当前没有可推送的上一条回答"}, status_code=422)
        result = {"tool":"feishu_publish_preview","content":content,"configured":bool(result.get("configured")),"requires_confirmation":True}
    if tool_name not in {"spreadsheet_query", "knowledge_retrieval", "data_quality_check", "feishu_publish_preview"}:
        return JSONResponse({"error":"工具结果类型不受支持"}, status_code=422)
    state = sessions.setdefault(payload.session_id, {"history": []})
    answer_system = SYSTEM + "根据已选择工具的结果回答。spreadsheet_query：当前上传文件本身就是 CRM 质检问题数据，issue_type 为空表示全部 CRM 已识别问题记录，不要要求用户再指定问题类型。knowledge_retrieval：只能依据 sources 回答并简要注明资料来源。data_quality_check：先说文件是否可分析，再列缺失字段或关键空值。feishu_publish_preview：说明已准备好上一条回答，提示用户点击页面上的‘推送飞书’确认按钮，不得声称已经发送。"
    material = {"question":payload.question,"plan":payload.plan,"result":result,"recent":state.get("history",[])[-3:]}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post("https://api.deepseek.com/chat/completions", headers={"Authorization":f"Bearer {API_KEY}"}, json={"model":MODEL,"messages":[{"role":"system","content":answer_system},{"role":"user","content":json.dumps(material,ensure_ascii=False)}],"thinking":{"type":"disabled"},"stream":False,"max_tokens":1000})
    except httpx.HTTPError:
        logger.exception("answer_model_request_failed")
        return JSONResponse({"error":"模型服务暂时不可用，请稍后重试"}, status_code=502)
    if response.status_code >= 400:
        return JSONResponse({"error":upstream_error(response, "回答生成失败，请稍后重试")}, status_code=502)
    try:
        answer = response.json()["choices"][0]["message"].get("content","").replace("**","")
    except (ValueError, TypeError, KeyError, IndexError):
        logger.exception("answer_model_response_invalid")
        return JSONResponse({"error":"模型返回格式异常，请重试"}, status_code=502)
    history_result = result.get("rows",[])[:10] if isinstance(result.get("rows"), list) else {"tool":tool_name}
    state["history"] = (state.get("history",[]) + [{"question":payload.question,"plan":payload.plan,"result":history_result,"answer":answer}])[-6:]
    return JSONResponse({"answer":answer,"tool":tool_name,"tool_result":result,"validation":{"valid":True}})


async def call_deepseek(question: str, context: str, knowledge: list[dict[str, str]], tool_result: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    if not API_KEY:
        return "后端尚未配置 DEEPSEEK_API_KEY。你仍可以使用页面内的确定性分析功能。", [x["source"] for x in knowledge]
    material = []
    if context:
        material.append(f"当前本地分析结果：\n{context}")
    if tool_result:
        material.append("已校验的确定性工具结果（优先依据）：\n" + json.dumps(tool_result, ensure_ascii=False))
    if knowledge:
        material.append("相关业务资料：\n" + "\n\n".join(f"[{x['source']}]\n{x['text']}" for x in knowledge))
    material.append(f"用户问题：{question}")
    payload = {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(material)}], "stream": False, "max_tokens": 1200}
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post("https://api.deepseek.com/chat/completions", headers={"Authorization": f"Bearer {API_KEY}"}, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(response.json().get("error", {}).get("message", "DeepSeek API 调用失败"))
    return response.json()["choices"][0]["message"]["content"], [x["source"] for x in knowledge]


async def call_deepseek_function_calling(question: str, context: str, history: list[dict[str, str]] | None = None) -> tuple[str, str, dict[str, Any] | None, list[str]]:
    """Two-pass DeepSeek flow: select tool, execute locally, then explain result."""
    if not API_KEY:
        selected = choose_tool(question, context)
        return "后端尚未配置 DEEPSEEK_API_KEY。你仍可以使用页面内的确定性分析功能。", selected["tool"], selected.get("result"), []
    headers = {"Authorization": f"Bearer {API_KEY}"}
    preferred = choose_tool(question, context).get("tool")
    memory = ""
    if history:
        memory = "\n最近对话仅用于理解省略主语，不得当作统计来源：\n" + json.dumps(history[-6:], ensure_ascii=False)
    base = [{"role":"system", "content": SYSTEM + "必须先选择一个主工具；数据问题调用确定性分析工具，规则问题调用 knowledge_retrieval。最终只回答用户明确问到的指标和范围，不要主动追加其他省区、站长摘要或无关排名。不得自行计算或改写统计数字。"}, {"role":"user", "content": f"当前本地分析摘要：\n{context}{memory}\n\n用户问题：{question}"}]
    async with httpx.AsyncClient(timeout=45) as client:
        # Disable reasoning mode for the planning pass: DeepSeek thinking mode
        # cannot be combined reliably with forced tool selection.
        # A standalone ERP is an unambiguous lookup intent.  Restrict the
        # available tools for this one case so the model cannot mistake it for
        # a generic station ranking request.
        available_tools = TOOL_DEFINITIONS + [KNOWLEDGE_TOOL]
        if preferred == "station_lookup":
            # An explicit ERP is an unambiguous lookup. Other questions remain
            # available to the model so it can interpret intent and constraints.
            available_tools = [item for item in TOOL_DEFINITIONS if item["function"]["name"] == "station_lookup"]
        first = await client.post("https://api.deepseek.com/chat/completions", headers=headers, json={"model":MODEL,"messages":base,"tools":available_tools,"tool_choice":"required","thinking":{"type":"disabled"},"stream":False,"max_tokens":600})
        if first.status_code >= 400: raise RuntimeError(first.json().get("error",{}).get("message","DeepSeek 工具选择失败"))
        message = first.json()["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls: raise RuntimeError("模型未返回工具调用，已拒绝使用未经验证的数字")
        ordered_calls = sorted(calls, key=lambda item: 0 if item.get("function",{}).get("name") == preferred else 1)
        results = []
        tool_messages = []
        for index, call in enumerate(ordered_calls):
            name = call.get("function",{}).get("name","")
            try: arguments = json.loads(call.get("function",{}).get("arguments") or "{}")
            except json.JSONDecodeError: arguments = {}
            # Validate the model's selected tool against the deterministic
            # intent guard. A station-ranking question must not be answered
            # with an issue-type ranking just because words like “虚假” or
            # “违规” resemble a CRM issue label.
            if preferred == "station_summary" and name == "problem_type_ranking":
                name = "station_summary"
                arguments = {}
                call.setdefault("function", {})["name"] = name
            # The ERP was supplied by the user, so preserve that explicit
            # condition instead of accepting a model-invented account.
            if name == "station_lookup" and extract_erp(question):
                arguments["erp"] = extract_erp(question)
            if name in {"problem_type_ranking", "station_summary", "generate_bulletin_summary"} and not arguments.get("province"):
                province = infer_province(question, context)
                if province: arguments["province"] = province
            if name == "station_summary" and not arguments.get("date"):
                match = re.search(r"(\d{1,2})[-/.月](\d{1,2})", question)
                if match:
                    year = datetime.now().year
                    arguments["date"] = f"{year}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
            if name == "station_summary" and not arguments.get("top_n"):
                top_match = re.search(r"(?:前|top\s*)(\d+)", question, re.I)
                chinese_top = re.search(r"前([一二三四五六七八九十])", question)
                chinese_numbers = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10}
                if top_match:
                    arguments["top_n"] = int(top_match.group(1))
                elif chinese_top:
                    arguments["top_n"] = chinese_numbers[chinese_top.group(1)]
            if name == "knowledge_retrieval":
                query = arguments.get("query") if isinstance(arguments, dict) else question
                docs = retrieve(query or question)
                result = {"tool":"knowledge_retrieval", "query":query or question, "sources":docs}
            else:
                result = execute_tool(name, arguments if isinstance(arguments,dict) else {}, context)
            validation = result.get("validation") or validate_tool_result(result)
            if not validation.get("valid"): raise RuntimeError("确定性工具结果校验失败")
            results.append((name, result))
            if index > 0:
                result = {"tool": name, "validation": {"valid": True}, "note": "本问题只采用主工具结果，请忽略此辅助调用结果。"}
            tool_messages.append({"role":"tool","tool_call_id":call.get("id",""),"name":name,"content":json.dumps(result,ensure_ascii=False)})
        name, result = results[0]
        assistant_message = {"role":"assistant", "content":message.get("content") or "", "tool_calls":message.get("tool_calls")}
        if message.get("reasoning_content") is not None:
            assistant_message["reasoning_content"] = message["reasoning_content"]
        second_messages = base + [assistant_message] + tool_messages
        second = await client.post("https://api.deepseek.com/chat/completions", headers=headers, json={"model":MODEL,"messages":second_messages,"thinking":{"type":"disabled"},"stream":False,"max_tokens":1200})
        if second.status_code >= 400: raise RuntimeError(second.json().get("error",{}).get("message","DeepSeek 结果解释失败"))
        answer = second.json()["choices"][0]["message"].get("content","")
        # Low-confidence fallback: a missing ERP is a factual tool outcome.
        # Do not let the model fill that gap with guesses about Top lists,
        # truncation, other provinces, or unverified problem types.
        if name == "station_lookup" and not result.get("found"):
            requested_erp = str(result.get("erp") or extract_erp(question) or "该 ERP")
            answer = (
                f"在当前上传文件的完整 ERP 索引中，未找到“{requested_erp}”的 CRM 已识别质检记录。"
                "这不代表该站长没有问题，只表示本次上传数据中没有匹配到该 ERP；请核对账号拼写、大小写和导出范围后再查询。"
            )
        sources = [item.get("source", "") for item in result.get("sources", [])] if name == "knowledge_retrieval" else []
        return answer, name, result, sources


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "build_version": BUILD_VERSION, "model_configured": bool(API_KEY), "knowledge_documents": len(list(KNOWLEDGE.glob("*.md"))), "langgraph": supervise("测试路由")["langgraph"], "rag_mode": os.getenv("RAG_BACKEND", "auto"), "feishu": get_feishu_status()}


@app.get("/api/feishu/status")
async def feishu_status() -> dict[str, Any]:
    """Return configuration readiness without exposing credentials or target IDs."""
    return get_feishu_status()


@app.post("/api/feishu/send")
async def feishu_send(payload: FeishuSendRequest) -> JSONResponse:
    """Publish one explicitly confirmed assistant answer through official MCP."""
    if not payload.confirmed:
        return JSONResponse({"error": "发送前必须由用户确认"}, status_code=400)
    status = get_feishu_status()
    if not status["configured"]:
        return JSONResponse(
            {"error": "飞书推送尚未配置完成", "missing": status["missing"], "runtime_available": status["runtime_available"]},
            status_code=409,
        )
    started = time.perf_counter()
    try:
        result = await send_feishu_message(payload.content)
    except Exception as exc:
        logger.exception("feishu_publish_failed")
        audit({"session_id": payload.session_id, "action": "feishu_publish", "ok": False, "error_type": type(exc).__name__})
        return JSONResponse({"error": "飞书推送失败", "detail": str(exc)}, status_code=502)
    elapsed = round((time.perf_counter() - started) * 1000)
    audit({"session_id": payload.session_id, "action": "feishu_publish", "ok": True, "tool": result["tool"], "elapsed_ms": elapsed})
    return JSONResponse({**result, "elapsed_ms": elapsed})


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> JSONResponse:
    started = time.perf_counter()
    state = sessions.setdefault(payload.session_id, {"history": []})
    context = attach_erp_lookup(payload.context, payload.erp_lookup)
    selected = choose_tool(payload.question, context)
    try:
        answer, tool_name, tool_result, sources = await call_deepseek_function_calling(payload.question, context, state.get("history", []))
    except Exception as exc:
        logger.exception("assistant_call_failed")
        return JSONResponse({"error":"模型调用失败","detail":str(exc),"route":selected["tool"],"tool_result":selected.get("result")}, status_code=502)
    state["last_question"] = payload.question
    state["history"] = (state.get("history", []) + [{"question": payload.question, "route": selected["tool"]}])[-8:]
    elapsed = round((time.perf_counter() - started) * 1000)
    validation = (tool_result or {}).get("validation") if isinstance(tool_result, dict) else selected.get("validation")
    logger.info("assistant_call route=%s tool=%s validated=%s sources=%s elapsed_ms=%s", route(payload.question), tool_name, (validation or {}).get("valid"), len(sources), elapsed)
    audit({"session_id": payload.session_id, "route": route(payload.question), "tool": tool_name, "validated": (validation or {}).get("valid"), "source_count": len(sources), "elapsed_ms": elapsed})
    return JSONResponse({"answer": answer, "sources": sorted(set(sources)), "route": tool_name, "tool": tool_name, "tool_result": tool_result, "validation": validation, "elapsed_ms": elapsed})


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """SSE endpoint; frontend can adopt it without changing the normal endpoint."""
    async def events():
        yield f"data: {json.dumps({'type': 'status', 'text': '正在识别问题…'}, ensure_ascii=False)}\n\n"
        if await request.is_disconnected():
            return
        context = attach_erp_lookup(payload.context, payload.erp_lookup)
        selected = choose_tool(payload.question, context)
        knowledge = retrieve(payload.question) if selected["tool"] == "knowledge_retrieval" else []
        yield f"data: {json.dumps({'type': 'status', 'text': '正在检索业务规则…' if knowledge else '正在整理分析结果…'}, ensure_ascii=False)}\n\n"
        try:
            if selected["tool"] in {"knowledge_retrieval", "fallback"}:
                answer, sources = await call_deepseek(payload.question, context, knowledge, selected.get("result"))
                tool_name, tool_result = selected["tool"], selected.get("result")
            else:
                yield f"data: {json.dumps({'type': 'status', 'text': '模型正在选择分析工具…'}, ensure_ascii=False)}\n\n"
                answer, tool_name, tool_result, sources = await call_deepseek_function_calling(payload.question, context)
            yield f"data: {json.dumps({'type': 'answer', 'answer': answer, 'tool': tool_name, 'tool_result': tool_result, 'sources': sorted(set(sources))}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-store", "X-Assistant-Build": BUILD_VERSION})


@app.get("/{asset:path}")
async def assets(asset: str) -> FileResponse:
    target = (ROOT / asset).resolve()
    if ROOT not in target.parents or not target.is_file():
        return FileResponse(ROOT / "index.html")
    return FileResponse(target, headers={"Cache-Control": "no-store", "X-Assistant-Build": BUILD_VERSION})
