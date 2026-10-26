# 工具、CLI、MCP、Skill 与关联项目交接

## 主项目

- GitHub：<https://github.com/mjx2794247173-gif/visit-quality-report-tool>
- 本地京ME版：`D:\\mengjiaxi.1\\Documents\\ChatGPT\\自动化选案例\\visit-quality-report-tool-jingme-local`
- 公开飞书版：`D:\\mengjiaxi.1\\Documents\\ChatGPT\\自动化选案例\\github-visit-quality-report-tool`

## 京ME CLI

本项目使用的京ME工具不是 OpenClaw，也不是一个单独的前端 MCP；实际发送链路是：

```text
网页 → FastAPI /api/jingme/send → 本机 jdme CLI → 京ME OpenAPI
```

工具名：`jdme`，由 Oxygen/o2 管理。常用检查命令：

```powershell
o2 search jdme
o2 info jdme
o2 skill jdme
jdme --help
jdme doctor --json
jdme auth whoami
```

发送文本：

```powershell
jdme message.send-text --input '{"erp":"mengjiaxi.1","content":"测试"}' --dry-run
jdme message.send-text --input '{"group_id":"10204738891","content":"测试"}' --dry-run
```

个人 ERP 和群 ID 必须二选一。群聊不是在“可用范围”里添加，而是要求机器人已经加入目标群，然后使用 `group_id` 发送；个人 ERP 则需要在京ME开放平台应用发布版本的“可用范围”中加入。

## 京ME Skill

通过以下命令读取完整 Skill：

```powershell
o2 skill jdme
```

Skill 主要覆盖：`message.send-text`、`message.send-card`、`message.send-sticky`、消息撤回、群创建、群成员管理、群查询、群成员查询、成员检查、用户授权等。重要错误：

- `99990128`：接口权限不足，需要申请对应接口权限；
- `20100012`：不在发送范围，需要“上线发布 → 发布新版本 → 选择可用范围”；
- `DELEGATION_REQUIRED`：需要人工授权；
- `AUTH_CONSENT_REQUIRED`：需要用户同意授权。

京ME凭证由 `jdme auth login` 或本机 o2 配置管理，不得提交 Git。默认配置位置为用户目录下的 `.config/jdme/config.json`，也可以使用 `JME_*` 环境变量。

## 京ME官方文档

当前实际使用的接口文档：

<https://me.jd.com/openplatform/docs?docs=%2Fdocs%2F7HVfrbOWhceS4Xasq50I%2F8QPvtQudnyw6eFHAiNDz%2FDHQgGtDpQbfBrIf5mvmC&activeTab=server>

文档的“通过机器人发送消息”章节说明：发送个人使用 `erp`，发送群使用 `groupId`/CLI 对应的 `group_id`；`20100012` 的解决办法是发布新版本并选择可用范围。

## MCP 现状

- 本地京ME发送目前没有专用 MCP，不能把 `jdme` CLI 误写成 MCP。
- 公开飞书版使用飞书官方 MCP/适配器，代码入口主要在 `assistant/backend/feishu.py` 和 `assistant/backend/main.py`。
- 两版的业务分析和推送弹窗必须一致；只有最终发送层不同：本地调用 `jdme`，公开版调用飞书。
- 如果未来接入京ME MCP，必须先确认真实 MCP 名称、工具 schema、权限和发送范围，再替换最后的 transport adapter，不能重写上层统计和 Agent。

## Skill 库相关

项目自身主要参考/使用的本地 Skill：

- `xvjiabaifang-ai-assistant`：自然语言拜访质量助手架构与维护规范；
- `xvjiabaifangtongbao`：拜访通报的数据口径、Excel 字段、筛选和通报逻辑；
- `frontend-design`：前端界面设计指导；
- `jdme`：通过 `o2 skill jdme` 读取的京ME CLI Skill；
- `spreadsheets`：涉及 Excel 处理时使用的表格规则。

## 音乐对话 Agent 项目

用户此前提到过“音乐对话 Agent”项目，但当前主项目目录、本机已发现的 Git 仓库和可读取的 Codex 项目列表中没有定位到该项目的确定仓库地址或本地目录，因此不能编造链接。接手 Agent 需要用户补充该项目的 Git 地址或项目名称后，才能把它写成准确交接链接。

当前能确认的同一工作区其他项目不是音乐对话 Agent：

- `D:\\mengjiaxi.1\\Documents\\ChatGPT\\1\\portfolio-fieldpulse` 是“区域服务运营地图”公开演示项目，不是音乐 Agent；
- `D:\\mengjiaxi.1\\Documents\\ChatGPT\\自动化选案例` 是当前拜访质量分析项目。

拿到音乐项目链接后，应补充：仓库地址、在线 Demo、启动命令、是否网页/App、模型和音频服务、MCP/Skill 依赖、当前完成度、未完成需求和面试演示路径。
