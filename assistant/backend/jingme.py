"""Safe JingME notification adapter backed by the local o2 jdme CLI.

This module deliberately contains no JingME credentials, internal URLs, or
hard-coded recipients.  The CLI owns authentication; this adapter only sends
validated, deterministic analysis summaries after explicit confirmation.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from typing import Any, Protocol

MAX_MESSAGE_CHARS = 4000


class JingMeAdapter(Protocol):
    async def send_text(
        self,
        *,
        analysis_result: dict[str, Any],
        erp: str | None = None,
        group_id: str | None = None,
        at_erps: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]: ...


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_jingme_status() -> dict[str, Any]:
    """Return readiness metadata without exposing credentials or recipients."""
    command = "o2.cmd" if os.name == "nt" else "o2"
    runtime_available = shutil.which(command) is not None
    enabled = _setting("JINGME_ENABLED", "false").lower() in {"1", "true", "yes"}
    env_auth = all(_setting(name) for name in (
        "JME_APP_KEY", "JME_APP_SECRET", "JME_OPEN_TEAM_ID", "JME_ROBOT_ID"
    ))
    config_path = os.path.join(os.path.expanduser("~"), ".config", "jdme", "config.json")
    local_auth = os.path.isfile(config_path)
    return {
        "enabled": enabled,
        "runtime_available": runtime_available,
        "credentials_configured": env_auth or local_auth,
        "configured": enabled and runtime_available and (env_auth or local_auth),
        "missing": (["JINGME_ENABLED"] if not enabled else [])
        + (["o2/jdme"] if not runtime_available else [])
        + (["京ME认证"] if not (env_auth or local_auth) else []),
        "tool": "message.send-text",
    }


def build_jingme_message(analysis_result: dict[str, Any]) -> str:
    """Render only whitelisted deterministic result fields into a message."""
    if not isinstance(analysis_result, dict) or not analysis_result.get("tool"):
        raise ValueError("缺少已校验的结构化分析结果")
    tool = str(analysis_result["tool"])
    lines = ["拜访质量分析通报", f"分析工具：{tool}"]
    for key in ("province", "date", "date_range", "rows", "metric", "issue_type"):
        value = analysis_result.get(key)
        if value not in (None, ""):
            lines.append(f"{key}：{value}")
    if isinstance(analysis_result.get("ranking"), list):
        lines.append("问题类型排名：")
        for index, item in enumerate(analysis_result["ranking"][:10], 1):
            if isinstance(item, dict):
                label = item.get("issue_type") or item.get("type") or item.get("name") or "未命名"
                count = item.get("count", item.get("visits", item.get("value", 0)))
                lines.append(f"{index}. {label}：{count}")
    if isinstance(analysis_result.get("stations"), list):
        lines.append("站长排名：")
        for index, item in enumerate(analysis_result["stations"][:10], 1):
            if isinstance(item, dict):
                erp = item.get("erp", "匿名ERP")
                visits = item.get("visits", item.get("count", 0))
                lines.append(f"{index}. {erp}：{visits}")
    if isinstance(analysis_result.get("problem_type_ranking"), list):
        lines.append("问题类型排名：")
        for index, item in enumerate(analysis_result["problem_type_ranking"][:10], 1):
            if isinstance(item, dict):
                label = item.get("issue_type") or item.get("type") or item.get("name") or "未命名"
                count = item.get("count", item.get("visits", item.get("value", 0)))
                lines.append(f"{index}. {label}：{count}")
    if analysis_result.get("disclaimer"):
        lines.append(str(analysis_result["disclaimer"]))
    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError(f"京ME通报不能超过 {MAX_MESSAGE_CHARS} 个字符")
    return text


class O2JingMeAdapter:
    def __init__(self, runner: Any | None = None):
        self.runner = runner or _run_o2

    async def send_text(self, *, analysis_result: dict[str, Any], erp: str | None = None,
                        group_id: str | None = None, at_erps: list[str] | None = None,
                        dry_run: bool = False) -> dict[str, Any]:
        status = get_jingme_status()
        if not status["configured"] and not dry_run:
            raise RuntimeError("京ME未配置完成：" + "、".join(status["missing"]))
        group_id = group_id or _setting("JINGME_GROUP_ID") or None
        if bool(erp) == bool(group_id):
            raise ValueError("京ME目标必须且只能是 ERP 或群")
        request: dict[str, Any] = {"content": build_jingme_message(analysis_result)}
        request["erp" if erp else "group_id"] = erp or group_id
        if at_erps:
            request["at_erps"] = [str(value) for value in at_erps[:20]]
        robot_id = _setting("JINGME_DEFAULT_ROBOT_ID")
        if robot_id:
            request["robot_id"] = robot_id
        result = await asyncio.to_thread(self.runner, request, dry_run)
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise RuntimeError("京ME发送失败")
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {"success": True, "channel": "jingme", "packet_id": data.get("packet_id"), "dry_run": bool(dry_run)}


class JingMeMockAdapter:
    async def send_text(self, *, analysis_result: dict[str, Any], erp: str | None = None,
                        group_id: str | None = None, at_erps: list[str] | None = None,
                        dry_run: bool = False) -> dict[str, Any]:
        # Rendering validates that the payload is deterministic even in mock mode.
        build_jingme_message(analysis_result)
        return {"success": True, "channel": "jingme-mock", "message": "已模拟发送京ME通报", "dry_run": True}


def _run_o2(request: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    command = "o2.cmd" if os.name == "nt" else "o2"
    args = [command, "launch", "jdme", "--", "message.send-text", "--input", json.dumps(request, ensure_ascii=False), "--json"]
    if dry_run:
        args.append("--dry-run")
    completed = subprocess.run(args, capture_output=True, text=True, timeout=45, check=False)
    if completed.returncode != 0:
        raise RuntimeError("京ME CLI调用失败")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("京ME CLI返回格式异常") from exc


def get_jingme_adapter() -> JingMeAdapter:
    provider = _setting("NOTIFICATION_PROVIDER", "feishu").lower()
    return JingMeMockAdapter() if provider == "jingme-mock" else O2JingMeAdapter()
