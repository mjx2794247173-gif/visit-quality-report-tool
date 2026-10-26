# 工具、CLI、MCP、Skill 与关联项目交接

主仓库：<https://github.com/mjx2794247173-gif/visit-quality-report-tool>

京ME CLI 使用说明、官方文档、MCP 边界、Skill 列表和音乐对话 Agent 项目定位见本仓库的 `TOOLS_HANDOFF.md`。公开版只保留飞书发送适配器；京ME凭证、内部 URL、机器人 ID、群 ID 和真实 ERP 不得提交 Git。两版必须共享同一套分析、筛选、统计、Agent、回答和推送弹窗逻辑，只在最终发送层分别接入飞书和京ME。

## 京ME CLI 与 Skill

本公开版不执行真实京ME发送；本地版的链路是“网页 → FastAPI `/api/jingme/send` → `jdme` CLI → 京ME OpenAPI”。工具由 Oxygen/o2 管理，读取说明：

```powershell
o2 search jdme
o2 info jdme
o2 skill jdme
jdme --help
jdme doctor --json
```

`message.send-text` 支持 `erp` 或 `group_id` 二选一；群聊要求机器人已经在目标群中，个人 ERP 需要在京ME应用发布版本的“可用范围”中。`20100012` 表示不在发送范围，需要“上线发布 → 发布新版本 → 选择可用范围”。京ME认证、密钥、机器人 ID、群 ID 和真实 ERP 不得提交本仓库。

京ME官方接口文档：<https://me.jd.com/openplatform/docs?docs=%2Fdocs%2F7HVfrbOWhceS4Xasq50I%2F8QPvtQudnyw6eFHAiNDz%2FDHQgGtDpQbfBrIf5mvmC&activeTab=server>

## MCP 现状

京ME当前没有接入专用 MCP，`jdme` 是 CLI，不要把两者混写。公开版使用飞书官方 MCP/适配器，主要入口为 `assistant/backend/feishu.py` 和 `assistant/backend/main.py`。未来若接入京ME MCP，只能替换最终发送 transport adapter，不能改动公共 Excel、Agent、回答和推送弹窗逻辑。

## Skill

相关 Skill 包括：`xvjiabaifang-ai-assistant`、`xvjiabaifangtongbao`、`frontend-design`、`spreadsheets`，以及通过 `o2 skill jdme` 读取的京ME CLI Skill。

## 音乐对话 Agent

当前主项目目录、本机已发现的 Git 仓库和可读取的 Codex 项目列表中没有定位到“音乐对话 Agent”的确定仓库地址或本地目录，因此这里不能编造链接。已确认 `D:\\mengjiaxi.1\\Documents\\ChatGPT\\1\\portfolio-fieldpulse` 是区域服务运营地图，不是音乐 Agent。拿到音乐项目的 Git 地址或准确项目名后，应补充其仓库、Demo、启动命令、模型/音频服务、MCP/Skill 依赖和未完成需求。
