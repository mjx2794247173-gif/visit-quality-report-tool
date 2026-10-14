"""Restricted Feishu message publisher backed by the official Lark MCP.

Only ``im.v1.message.create`` is exposed to this application.  The target
recipient is configured on the server and can never be supplied by the model
or browser request.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MCP_TOOL = "im.v1.message.create"
DEFAULT_PACKAGE = "@larksuiteoapi/lark-mcp@0.5.1"
ALLOWED_RECEIVE_ID_TYPES = {"chat_id", "open_id", "union_id", "user_id", "email"}
MAX_MESSAGE_CHARS = 4000


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_feishu_status() -> dict[str, Any]:
    required = {
        "FEISHU_APP_ID": _setting("FEISHU_APP_ID"),
        "FEISHU_APP_SECRET": _setting("FEISHU_APP_SECRET"),
        "FEISHU_RECEIVE_ID": _setting("FEISHU_RECEIVE_ID"),
    }
    missing = [name for name, value in required.items() if not value]
    command = "npx.cmd" if os.name == "nt" else "npx"
    runtime_available = shutil.which(command) is not None
    return {
        "configured": not missing and runtime_available,
        "runtime_available": runtime_available,
        "missing": missing,
        "receive_id_type": _setting("FEISHU_RECEIVE_ID_TYPE", "chat_id"),
        "tool": MCP_TOOL,
    }


def validate_message(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        raise ValueError("没有可推送的回答内容")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError(f"推送内容不能超过 {MAX_MESSAGE_CHARS} 个字符")
    return text


def build_message_arguments(content: str) -> dict[str, Any]:
    """Build the only payload shape allowed to reach the MCP tool."""
    text = validate_message(content)
    receive_id = _setting("FEISHU_RECEIVE_ID")
    receive_id_type = _setting("FEISHU_RECEIVE_ID_TYPE", "chat_id")
    if not receive_id:
        raise RuntimeError("尚未配置 FEISHU_RECEIVE_ID")
    if receive_id_type not in ALLOWED_RECEIVE_ID_TYPES:
        raise RuntimeError("FEISHU_RECEIVE_ID_TYPE 配置无效")
    return {
        "params": {"receive_id_type": receive_id_type},
        "data": {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
            "uuid": str(uuid.uuid4()),
        },
    }


def _server_parameters() -> StdioServerParameters:
    status = get_feishu_status()
    if not status["configured"]:
        missing = "、".join(status["missing"]) or "Node.js/npx"
        raise RuntimeError(f"飞书推送尚未配置完成：{missing}")
    child_env = os.environ.copy()
    child_env.update(
        {
            "APP_ID": _setting("FEISHU_APP_ID"),
            "APP_SECRET": _setting("FEISHU_APP_SECRET"),
            "LARK_TOOLS": MCP_TOOL,
            "LARK_DOMAIN": _setting("FEISHU_DOMAIN", "https://open.feishu.cn"),
            "LARK_TOKEN_MODE": _setting("FEISHU_TOKEN_MODE", "tenant_access_token"),
        }
    )
    command = "npx.cmd" if os.name == "nt" else "npx"
    package = _setting("FEISHU_MCP_PACKAGE", DEFAULT_PACKAGE)
    return StdioServerParameters(
        command=command,
        args=["-y", package, "mcp", "-t", MCP_TOOL, "-c", "dot", "-l", "zh"],
        env=child_env,
    )


async def send_feishu_message(content: str) -> dict[str, Any]:
    """Send one validated text message through the official Feishu MCP."""
    arguments = build_message_arguments(content)
    async with stdio_client(_server_parameters()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            if MCP_TOOL not in {tool.name for tool in tools.tools}:
                raise RuntimeError("官方飞书 MCP 未返回消息发送工具")
            result = await session.call_tool(MCP_TOOL, arguments=arguments)
    if result.isError:
        details = "；".join(
            item.text for item in result.content if getattr(item, "type", "") == "text"
        )
        raise RuntimeError(details or "飞书 MCP 发送失败")
    structured = result.structuredContent if isinstance(result.structuredContent, dict) else {}
    return {
        "ok": True,
        "tool": MCP_TOOL,
        "receive_id_type": arguments["params"]["receive_id_type"],
        "message_id": _find_message_id(structured),
    }


def _find_message_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("message_id", "messageId"):
            if value.get(key):
                return str(value[key])
        for item in value.values():
            found = _find_message_id(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_message_id(item)
            if found:
                return found
    return None
