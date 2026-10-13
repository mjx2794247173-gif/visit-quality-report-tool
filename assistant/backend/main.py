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
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from .tools import attach_erp_lookup, choose_tool, TOOL_DEFINITIONS, execute_tool, extract_erp, validate_tool_result
from .supervisor import supervise

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "server" / ".env", override=True)
KNOWLEDGE = ROOT / "knowledge"
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

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
            # The ERP was supplied by the user, so preserve that explicit
            # condition instead of accepting a model-invented account.
            if name == "station_lookup" and extract_erp(question):
                arguments["erp"] = extract_erp(question)
            if name in {"problem_type_ranking", "station_summary", "generate_bulletin_summary"} and not arguments.get("province"):
                province = infer_province(question, context)
                if province: arguments["province"] = province
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
    return {"ok": True, "model_configured": bool(API_KEY), "knowledge_documents": len(list(KNOWLEDGE.glob("*.md"))), "langgraph": supervise("测试路由")["langgraph"], "rag_mode": os.getenv("RAG_BACKEND", "auto")}


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
    return FileResponse(ROOT / "index.html")


@app.get("/{asset:path}")
async def assets(asset: str) -> FileResponse:
    target = (ROOT / asset).resolve()
    if ROOT not in target.parents or not target.is_file():
        return FileResponse(ROOT / "index.html")
    return FileResponse(target)
