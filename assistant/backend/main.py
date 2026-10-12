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
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "server" / ".env")
KNOWLEDGE = ROOT / "knowledge"
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

app = FastAPI(title="虚假拜访问答助手", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
sessions: dict[str, dict[str, Any]] = {}


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    context: str = Field(default="", max_length=12000)
    session_id: str = Field(default="default", max_length=100)


def chunks(text: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for file in sorted(KNOWLEDGE.glob("*.md")):
        content = file.read_text(encoding="utf-8")
        parts = re.split(r"\n(?=##?\s)", content)
        result.extend({"source": file.name, "text": p.strip()} for p in parts if p.strip())
    return result


def retrieve(question: str, limit: int = 6) -> list[dict[str, str]]:
    terms = re.findall(r"[\u4e00-\u9fff]{2}|[a-zA-Z0-9_]{2,}", question.lower())
    scored = []
    for item in chunks(question):
        score = sum(item["text"].lower().count(term) for term in set(terms))
        if score:
            scored.append((score, item))
    return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]


def route(question: str) -> str:
    if re.search(r"字段|导出|CRM|规则|评分|口径|通报|怎么判定|上传", question, re.I):
        return "knowledge_qa"
    if re.search(r"哪个|哪位|谁|最多|连续|重复|问题|站长|客户", question):
        return "deterministic_analysis"
    return "fallback"


SYSTEM = (
    "你是省区虚假拜访质量分析助手。只能解释 CRM 已识别的质检问题，"
    "不能自行判断虚假、查看照片或编造统计结果。数据问题优先相信调用方提供的确定性分析结果；"
    "规则问题只依据提供的业务资料。先给结论，最后注明依据。"
)


async def call_deepseek(question: str, context: str, knowledge: list[dict[str, str]]) -> tuple[str, list[str]]:
    if not API_KEY:
        return "后端尚未配置 DEEPSEEK_API_KEY。你仍可以使用页面内的确定性分析功能。", [x["source"] for x in knowledge]
    material = []
    if context:
        material.append(f"当前本地分析结果：\n{context}")
    if knowledge:
        material.append("相关业务资料：\n" + "\n\n".join(f"[{x['source']}]\n{x['text']}" for x in knowledge))
    material.append(f"用户问题：{question}")
    payload = {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(material)}], "stream": False, "max_tokens": 1200}
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post("https://api.deepseek.com/chat/completions", headers={"Authorization": f"Bearer {API_KEY}"}, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(response.json().get("error", {}).get("message", "DeepSeek API 调用失败"))
    return response.json()["choices"][0]["message"]["content"], [x["source"] for x in knowledge]


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "model_configured": bool(API_KEY), "knowledge_documents": len(list(KNOWLEDGE.glob("*.md")))}


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> JSONResponse:
    started = time.perf_counter()
    knowledge = retrieve(payload.question) if route(payload.question) == "knowledge_qa" else []
    answer, sources = await call_deepseek(payload.question, payload.context, knowledge)
    sessions.setdefault(payload.session_id, {})["last_question"] = payload.question
    return JSONResponse({"answer": answer, "sources": sorted(set(sources)), "route": route(payload.question), "elapsed_ms": round((time.perf_counter() - started) * 1000)})


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """SSE endpoint; frontend can adopt it without changing the normal endpoint."""
    async def events():
        yield f"data: {json.dumps({'type': 'status', 'text': '正在识别问题…'}, ensure_ascii=False)}\n\n"
        if await request.is_disconnected():
            return
        knowledge = retrieve(payload.question) if route(payload.question) == "knowledge_qa" else []
        yield f"data: {json.dumps({'type': 'status', 'text': '正在检索业务规则…' if knowledge else '正在整理分析结果…'}, ensure_ascii=False)}\n\n"
        try:
            answer, sources = await call_deepseek(payload.question, payload.context, knowledge)
            yield f"data: {json.dumps({'type': 'answer', 'answer': answer, 'sources': sorted(set(sources))}, ensure_ascii=False)}\n\n"
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
