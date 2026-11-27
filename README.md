# 拜访质量分析智能助手

这是一个面向省区运营场景的自然语言分析 Agent：用户上传 CRM 质检 Excel 后，可以直接用自然语言提问，系统通过 LangGraph、Function Calling、确定性数据工具和 RAG 业务知识库完成分析，并生成可追溯的回答、通报预览和发布结果。

项目的主产品位于 [`assistant/`](assistant/)，根目录的静态页面是轻量的本地 Excel 分析入口，用于兼容简单筛选和通报场景。

## 核心能力

- 自然语言理解：识别省区、ERP、问题类型、日期、排序、Top N 和多轮追问条件
- 多 Agent 路由：数据分析、知识问答、质量边界、通报发布、追问澄清和越界拦截
- 确定性统计：由白名单工具执行筛选、分组、去重、排名和评分，模型不自行编造数字
- RAG 知识库：检索字段要求、统计口径、评分规则、业务边界和工具调用规范
- 多轮对话：保留经过校验的查询条件和结果摘要，支持上下文追问
- 通报工作流：统一筛选范围后选择“问答”或“通报”，展示预览并要求用户确认
- 发布适配：支持飞书发布预览；京ME适配说明见 [`docs/JINGME_SOP.md`](docs/JINGME_SOP.md)
- 安全边界：不看照片、不自行判断拜访真假、不把模型生成的数字当作 CRM 事实

## 快速体验

1. 打开 [`assistant/index.html`](assistant/index.html)，或按 [`assistant/README.md`](assistant/README.md) 启动本地服务。
2. 上传 CRM 导出的 `.xlsx` 或 `.csv`，也可以加载脱敏示例：[`assistant/sample_data/crm_visit_quality_demo.csv`](assistant/sample_data/crm_visit_quality_demo.csv)。
3. 设置省区和日期范围，选择“我要问答”或“我要通报”。
4. 使用自然语言提问，例如“谁的问题最多？”或“山东省区连续多天出现问题的站长是谁？”。
5. 生成通报后先检查预览，再由用户明确确认发布。

## 系统架构

```text
浏览器上传 Excel → 本地字段解析与确定性统计 → 自然语言问题
        → Intent Interpreter → LangGraph Supervisor
        → 数据工具 / RAG / 质量边界 / 通报工作流
        → 结果校验与回答审查 → 问答结果或用户确认后的发布
```

后端入口位于 [`assistant/backend/main.py`](assistant/backend/main.py)，白名单工具位于 [`assistant/backend/tools.py`](assistant/backend/tools.py)，公开评测集位于 [`assistant/evaluation/`](assistant/evaluation/)。

## 运行方式

详细启动、环境变量、测试和评测命令见 [`assistant/README.md`](assistant/README.md)。常用后端启动方式：

```powershell
py -3.12 -m uvicorn assistant.backend.main:app --host 127.0.0.1 --port 8788
```

启动后访问 `http://127.0.0.1:8788/`。需要模型回答时，在 `assistant/server/.env` 中配置模型服务密钥；真实密钥、机器人凭证和内部配置不得提交到仓库。

## 评测与质量保证

当前公开评测集包含 20 道案例：15 道单轮案例和 5 道多轮案例，覆盖数据查询、日期、省区比较、评分规则、字段要求、缺失字段、澄清、安全拦截和多轮追问。评测目标卡见 [`assistant/evaluation/EVALUATION_GOAL_CARD.md`](assistant/evaluation/EVALUATION_GOAL_CARD.md)。

## 数据与隐私

- CRM 原始 Excel 默认只在当前浏览器会话和本地后端处理
- 真实行级数据不得写入长期 RAG、日志、示例数据或 Git 历史
- 模型只能解释 CRM 已识别的质检问题，不能自行判断“虚假拜访”
- 发布工具必须经过预览和用户二次确认
- 公开仓库只保留脱敏配置、Mock/Dry-run 和接口抽象

## 兼容的本地通报入口

根目录 [`index.html`](index.html) 保留一个无需后端的静态 Excel 分析工具，可按日期、省区和拜访方式筛选数据，计算重点案例并生成通报。它是兼容入口，不是本项目的主要 Agent 产品。

在线静态预览：

`https://mjx2794247173-gif.github.io/visit-quality-report-tool/`

## 文档入口

- [`assistant/README.md`](assistant/README.md)：智能助手架构、启动和测试
- [`assistant/skill/`](assistant/skill/)：业务边界、统计口径和工具调用规范
- [`assistant/evaluation/`](assistant/evaluation/)：评测集与评测脚本
- [`docs/JINGME_SOP.md`](docs/JINGME_SOP.md)：京ME接入 SOP，分别面向使用者和 Agent
- [`HANDOFF.md`](HANDOFF.md)：项目交接和历史实现说明
