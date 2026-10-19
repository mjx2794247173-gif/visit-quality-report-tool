# 拜访质量分析智能助手

面向省区运营同学的拜访质量分析助手：上传 CRM 导出的虚假拜访 Excel 后，用自然语言查询站长、问题类型、连续日期和重复客户，并通过 RAG 解释评分规则、字段要求和通报口径。

## 当前架构

```text
用户自然语言问题
→ LangGraph Supervisor 选择专业 Agent
→ 专业 Agent 通过 Function Calling 生成结构化计划
→ 浏览器按照白名单计划计算当前 Excel
→ FastAPI 校验工具结果
→ DeepSeek 基于已验证结果生成回答
→ 独立验收回答完整性，必要时最多修复一次
→ 用户确认后生成飞书发布预览或发送
```

当前有四个专业 Agent：

- `data_agent`：省区、日期、ERP、问题类型、分组、指标和 Top N 查询。
- `knowledge_agent`：评分规则、字段说明、CRM 导出要求和统计口径。
- `quality_agent`：缺失字段、空值、日期范围和文件可分析性检查。
- `publishing_agent`：只生成最近一次已校验回答的飞书发布预览。

## 已完成功能

- 浏览器本地解析 Excel，真实 CRM 行级数据默认不上传、不写入知识库。
- 统计、去重、连续日期和评分由确定性程序完成；大模型只负责意图理解、规则检索和回答组织。
- FastAPI 提供工具化后端，包含普通问答接口和 SSE 流式接口。
- 数据分析问题使用标准 DeepSeek Function Calling：模型只选择白名单工具并生成筛选参数，FastAPI 执行本地工具、校验结构化结果，再让模型解释结果。
- LangGraph Supervisor 编排四个专业 Agent；Pydantic 严格校验 Agent 决策和查询计划，并通过独立 `validate_plan` 节点再次确认计划。
- 回答生成后由独立验收器检查是否覆盖用户范围和确定性结果；不完整时最多重生成一次。
- 规则知识采用关键词检索与向量检索并行、RRF 融合、模型 Rerank、相关性过滤、资料充分性校验和一次检索改写。
- 使用脱敏滚动记忆支持连续追问；只持久化查询条件，ERP 会在落盘前移除，SQLite 记录使用哈希会话键和 7 天 TTL。会话历史只保留工具名、行数、来源数量和资料充分性，不保存统计结果行。
- 本地模式默认不持久化会话；如需多进程或重启恢复，可设置 `PERSIST_SESSION_STATE=true` 开启 SQLite 会话状态。
- 稳定知识检索使用 SHA256 键、10 分钟 TTL 和 LRU 容量限制；不缓存真实 Excel 结果或最终回答。
- 阻塞型知识检索与 SQLite 读写通过线程卸载，避免卡住 FastAPI 事件循环。
- 每次规划和回答使用 Trace ID 关联，审计日志只记录白名单元数据，不保存问题原文和 CRM 行级数据。
- 使用飞书官方 OpenAPI MCP 将已校验回答推送到固定群聊；只开放消息发送工具，并要求用户二次确认。
- 建立 8 条脱敏自然语言黄金评测集，分别统计 Agent 路由、工具选择、查询参数、整体通过率、请求失败率和平均耗时。

### 知识资料充分性审查

Knowledge Agent 检索后不会立即回答。系统先把用户问题和检索片段交给独立的充分性审查模型，并通过 Pydantic 约束为 `is_sufficient` 和 `missing_information`：

```text
首次检索 → Rerank 与相关性过滤 → 充分性审查
├─ 资料充分：进入回答生成
└─ 资料不足：根据缺失信息改写查询 → 补充检索 → 再审查一次
   ├─ 资料充分：进入回答生成
   └─ 仍然不足：明确拒答并说明缺少什么
```

审查模型只能判断现有资料能否支持答案，不能使用自身知识补全事实。该节点主要防止“检索到了相关文字，但证据不足时模型仍然凭常识作答”的幻觉。

## 本地运行（Windows）

1. 安装 Python 3.12。
2. 双击或在 PowerShell 执行 `start-fastapi.ps1`。
3. 首次运行会安装 FastAPI 依赖，并自动创建 `server/.env`。
4. 在 `server/.env` 填入 `DEEPSEEK_API_KEY`。
5. 打开 <http://localhost:8787>。首次使用向量 RAG 可能需要下载中文 Embedding 模型；网络受限时会自动回退关键词检索。

### 可选：接入飞书群消息

1. 安装 Node.js 20 或更高版本。
2. 在飞书开放平台创建企业自建应用，启用机器人能力和发送消息权限，并把机器人加入目标群。
3. 获取目标群的 `chat_id`。
4. 在 `server/.env` 填写 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 和 `FEISHU_RECEIVE_ID`。
5. 重启 FastAPI。生成回答后点击“推送飞书”，确认预览即可发送。

后端固定使用官方 `@larksuiteoapi/lark-mcp`，且只启用 `im.v1.message.create`。浏览器不能修改目标群，模型也不能直接触发发送；真实凭证和群 ID 不得提交到 GitHub。

面试演示可直接上传 `sample_data/crm_visit_quality_demo.csv`（脱敏虚构数据），然后连续提问：

1. 哪些站长问题最多？
2. 谁连续多天出现问题？
3. 为什么 erp-demo-01 会排在重点站长前面？
4. CRM 导出需要哪些字段？

这组问题会同时展示本地统计、Function Calling、RAG 引用和同一会话的连续追问。

也可以手动运行：

```powershell
cd assistant
py -3.12 -m pip install -r backend/requirements.txt
py -3.12 -m uvicorn backend.main:app --host 127.0.0.1 --port 8787
```

接口：

- `GET /api/health`：检查服务和密钥状态
- `POST /api/plan`：运行多 Agent Graph，生成结构化工具计划
- `POST /api/answer`：校验浏览器工具结果并生成最终回答
- `POST /api/chat`：普通问答
- `POST /api/chat/stream`：SSE 流式问答
- `GET /api/feishu/status`：检查飞书 MCP 配置，不返回凭证或群 ID
- `POST /api/feishu/send`：确认后把一条已生成回答推送到固定飞书目标

数据分析链路约束：模型不得自行计算关键统计数字；工具执行只使用浏览器传入的聚合上下文，不接受模型提供的原始数据或任意代码。

调用日志写入 `server/assistant_calls.jsonl`，只保存时间、路由、工具名、校验状态、引用数量和耗时，不保存问题原文、CRM 行级记录或客户信息。设置 `RAG_BACKEND=keyword` 可强制使用轻量检索；默认优先使用 Chroma + `BAAI/bge-small-zh-v1.5`。

## 测试与 Agent 评测

必须先确认 Python 3.12，再运行测试；不要使用系统默认 `python`：

```powershell
py -0p
py -3.12 -m pytest assistant/backend -q
```

当前基线为 66 个自动化测试。自然语言评测会真实调用本地后端和模型：

```powershell
# 在仓库根目录运行全部 8 条黄金评测
py -3.12 -m assistant.backend.run_evaluation

# 只运行第一条，适合低成本冒烟验证
py -3.12 -m assistant.backend.run_evaluation --limit 1
```

评测分别报告 Agent 路由、工具选择、查询参数、整体通过率、请求失败率和平均耗时。日志用于还原一次真实请求，评测用于判断系统行为是否符合预期，两者用途不同。

## 示例问题

- 哪些站长连续多天出现问题？
- 哪个省区的拍照不规范最多？
- 哪些站长同时涉及两类问题？
- CRM 导出需要哪些字段？
- 重点站长评分怎么组成？

## 业务边界

助手不自行判断虚假拜访，不查看照片，不替代 CRM 的质检 AI。所有问题类型来自 CRM 导出的“质检问题类型”；模型不能直接执行任意 SQL，也不能把真实 CRM 行级记录写入长期知识库。

公开 GitHub Pages 页面仍作为演示入口；完整 FastAPI 版本用于本地下载运行和面试演示。

继续开发前请先阅读仓库根目录的 [`HANDOFF.md`](../HANDOFF.md) 和 [`AGENTS.md`](../AGENTS.md)。
