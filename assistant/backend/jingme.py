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

# JingME's provider-side limit is effectively stricter for Chinese text than
# Python's character count suggests. Keep a byte-safe budget for JSON/API
# transport and leave room for provider-side framing.
MAX_MESSAGE_CHARS = 600
MAX_MESSAGE_BYTES = 1800


class JingMeAdapter(Protocol):
    async def send_text(
        self,
        *,
        analysis_result: dict[str, Any],
        content: str | None = None,
        erp: str | None = None,
        group_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]: ...


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_jingme_status() -> dict[str, Any]:
    """Return readiness metadata without exposing credentials or recipients."""
    command = "o2.cmd" if os.name == "nt" else "o2"
    runtime_available = shutil.which(command) is not None or shutil.which("jdme.cmd" if os.name == "nt" else "jdme") is not None
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
        for index, item in enumerate(analysis_result["ranking"][:3], 1):
            if isinstance(item, dict):
                label = item.get("issue_type") or item.get("type") or item.get("name") or "未命名"
                count = item.get("count", item.get("visits", item.get("value", 0)))
                lines.append(f"{index}. {str(label)[:60]}：{count}")
    if isinstance(analysis_result.get("stations"), list):
        lines.append("站长排名：")
        for index, item in enumerate(analysis_result["stations"][:3], 1):
            if isinstance(item, dict):
                erp = item.get("erp", "匿名ERP")
                visits = item.get("visits", item.get("count", 0))
                lines.append(f"{index}. {str(erp)[:60]}：{visits}")
    if isinstance(analysis_result.get("problem_type_ranking"), list):
        lines.append("问题类型排名：")
        for index, item in enumerate(analysis_result["problem_type_ranking"][:3], 1):
            if isinstance(item, dict):
                label = item.get("issue_type") or item.get("type") or item.get("name") or "未命名"
                count = item.get("count", item.get("visits", item.get("value", 0)))
                lines.append(f"{index}. {str(label)[:60]}：{count}")
    text = "\n".join(lines)
    if len(text) <= MAX_MESSAGE_CHARS and len(text.encode("utf-8")) <= MAX_MESSAGE_BYTES:
        return text
    compact_lines = lines
    text = "\n".join(compact_lines)
    if len(text) <= MAX_MESSAGE_CHARS and len(text.encode("utf-8")) <= MAX_MESSAGE_BYTES:
        return text
    # Keep the structured summary and the first few ranked results. Never
    # slice arbitrary bytes or use model-generated numbers.
    summary = compact_lines[:]
    while len(summary) > 4:
        candidate = "\n".join(summary)
        if len(candidate) <= MAX_MESSAGE_CHARS and len(candidate.encode("utf-8")) <= MAX_MESSAGE_BYTES:
            return candidate
        summary.pop()
    text = "\n".join(summary)
    if len(text) <= MAX_MESSAGE_CHARS and len(text.encode("utf-8")) <= MAX_MESSAGE_BYTES:
        return text
    # Last-resort deterministic fallback. This deliberately excludes all
    # free-form explanation and ranking labels so a provider-side byte limit
    # can never turn a valid analysis into a failed notification.
    fallback = ["拜访质量通报", f"分析工具：{tool[:60]}"]
    for key in ("province", "date", "date_range", "rows", "metric", "issue_type"):
        value = analysis_result.get(key)
        if value not in (None, ""):
            fallback.append(f"{key}：{str(value)[:80]}")
    fallback_text = "\n".join(fallback)
    if len(fallback_text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        fallback_text = "\n".join(fallback[:4])
    return fallback_text


def split_jingme_message(content: str) -> list[str]:
    """Split an answer without rewriting it or changing any statistics."""
    text = str(content or "").strip()
    if not text:
        raise ValueError("京ME消息内容不能为空")
    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for character in text:
        encoded_size = len(character.encode("utf-8"))
        if current and (len(current) + 1 > MAX_MESSAGE_CHARS or current_bytes + encoded_size > MAX_MESSAGE_BYTES):
            chunks.append("".join(current))
            current = []
            current_bytes = 0
        current.append(character)
        current_bytes += encoded_size
    if current:
        chunks.append("".join(current))
    return chunks


class O2JingMeAdapter:
    def __init__(self, runner: Any | None = None):
        self.runner = runner or _run_o2

    async def send_text(self, *, analysis_result: dict[str, Any], content: str | None = None, erp: str | None = None,
                        group_id: str | None = None,
                        dry_run: bool = False) -> dict[str, Any]:
        status = get_jingme_status()
        if not status["configured"] and not dry_run:
            raise RuntimeError("京ME未配置完成：" + "、".join(status["missing"]))
        group_id = group_id or _setting("JINGME_GROUP_ID") or None
        if bool(erp) == bool(group_id):
            raise ValueError("京ME目标必须且只能是 ERP 或群")
        messages = split_jingme_message(content) if content is not None else [build_jingme_message(analysis_result)]
        target_key = "erp" if erp else "group_id"
        target_value = erp or group_id
        robot_id = _setting("JINGME_DEFAULT_ROBOT_ID")
        packet_ids: list[str] = []
        for message in messages:
            request: dict[str, Any] = {"content": message, target_key: target_value}
            if robot_id:
                request["robot_id"] = robot_id
            result = await asyncio.to_thread(self.runner, request, dry_run)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise RuntimeError("京ME发送失败")
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            if data.get("packet_id"):
                packet_ids.append(str(data["packet_id"]))
        return {"success": True, "channel": "jingme", "packet_id": packet_ids[-1] if packet_ids else None,
                "packet_ids": packet_ids, "message_count": len(messages), "dry_run": bool(dry_run)}


class JingMeMockAdapter:
    async def send_text(self, *, analysis_result: dict[str, Any], content: str | None = None, erp: str | None = None,
                        group_id: str | None = None,
                        dry_run: bool = False) -> dict[str, Any]:
        # Rendering validates that the payload is deterministic even in mock mode.
        split_jingme_message(content) if content is not None else build_jingme_message(analysis_result)
        return {"success": True, "channel": "jingme-mock", "message": "已模拟发送京ME通报", "dry_run": True}


def _run_o2(request: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    o2_command = shutil.which("o2.exe" if os.name == "nt" else "o2")
    jdme_command = shutil.which("jdme.cmd" if os.name == "nt" else "jdme")
    # When jdme is installed globally, prefer its verified entry point. The
    # registry-backed `o2 launch` may return an empty success while attempting
    # its own lazy install record on Windows.
    command = jdme_command or o2_command
    if not command:
        raise RuntimeError("未找到 o2 或 jdme 命令")
    args = ([command, "message.send-text"] if jdme_command else [command, "launch", "jdme", "--", "message.send-text"]) + ["--input", json.dumps(request, ensure_ascii=False), "--json"]
    if dry_run:
        args.append("--dry-run")
    completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45, check=False)
    # o2 can know a CLI from Registry while still missing its local install
    # record. If that specific lazy-install path fails, use the same installed
    # jdme entry point directly; never retry a real API/business failure.
    combined = f"{completed.stdout}\n{completed.stderr}".lower()
    if completed.returncode != 0 and ("lazy install" in combined or "not installed" in combined):
        direct = jdme_command or ("jdme.cmd" if os.name == "nt" else "jdme")
        direct_args = [direct, "message.send-text", "--input", json.dumps(request, ensure_ascii=False), "--json"]
        if dry_run:
            direct_args.append("--dry-run")
        completed = subprocess.run(direct_args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45, check=False)
    if completed.returncode != 0:
        detail = _safe_cli_error(completed.stdout, completed.stderr)
        raise RuntimeError(f"京ME CLI调用失败：{detail}")
    try:
        return json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        combined = f"{completed.stdout}\n{completed.stderr}".lower()
        if jdme_command and "lazy install" in combined:
            direct_args = [jdme_command, "message.send-text", "--input", json.dumps(request, ensure_ascii=False), "--json"]
            if dry_run:
                direct_args.append("--dry-run")
            direct = subprocess.run(direct_args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45, check=False)
            if direct.returncode == 0:
                try:
                    return json.loads(direct.stdout or "")
                except json.JSONDecodeError:
                    pass
        raise RuntimeError("京ME CLI返回格式异常") from exc


def _safe_cli_error(stdout: str | None, stderr: str | None) -> str:
    """Expose only a bounded provider error, never command args or secrets."""
    for raw in (stdout or "", stderr or ""):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or "JME_API_ERROR")[:80]
            message = str(error.get("message") or "京ME业务调用失败")[:240]
            return f"{code}：{message}"
    return "请运行 jdme doctor --json 检查认证和权限"


def get_jingme_adapter() -> JingMeAdapter:
    provider = _setting("NOTIFICATION_PROVIDER", "feishu").lower()
    return JingMeMockAdapter() if provider == "jingme-mock" else O2JingMeAdapter()
