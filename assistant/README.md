# 虚假拜访问答助手

面向省区运营同学的拜访质量分析助手：上传 CRM 导出的虚假拜访 Excel 后，用自然语言查询站长、问题类型、连续日期和重复客户，并通过 RAG 解释评分规则、字段要求和通报口径。

## 项目亮点

- 浏览器本地解析 Excel，真实 CRM 行级数据默认不上传、不写入知识库。
- 统计、去重、连续日期和评分由确定性程序完成；大模型只负责意图理解、规则检索和回答组织。
- FastAPI 提供工具化后端，包含普通问答接口和 SSE 流式接口。
- 数据分析问题使用标准 DeepSeek Function Calling：模型只选择白名单工具并生成筛选参数，FastAPI 执行本地工具、校验结构化结果，再让模型解释结果。
- LangGraph Supervisor 真实编排问题分流：规则/RAG、确定性分析和兜底三条分支，并在 `/api/health` 暴露是否加载成功。
- 知识库按 Markdown 文档维护，可接入 Chroma + 中文 Embedding；当前轻量运行也支持关键词回退。
- 会话状态记录当前问题和分析上下文，方便连续追问。

## 架构

```text
网页上传 Excel / 提问
        ↓
本地确定性分析工具（排名、连续天数、重复客户、评分）
        ↓
 DeepSeek Function Calling 选择白名单工具
        ↓
 FastAPI 执行工具并校验结构化结果
        ↓
 RAG 检索业务资料 / DeepSeek 解释
        ↓
答案与依据
```

## 本地运行（Windows）

1. 安装 Python 3.12。
2. 双击或在 PowerShell 执行 `start-fastapi.ps1`。
3. 首次运行会安装 FastAPI 依赖，并自动创建 `server/.env`。
4. 在 `server/.env` 填入 `DEEPSEEK_API_KEY`。
5. 打开 <http://localhost:8787>。首次使用向量 RAG 可能需要下载中文 Embedding 模型；网络受限时会自动回退关键词检索。

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
- `POST /api/chat`：普通问答
- `POST /api/chat/stream`：SSE 流式问答

数据分析链路约束：模型不得自行计算关键统计数字；工具执行只使用浏览器传入的聚合上下文，不接受模型提供的原始数据或任意代码。

调用日志写入 `server/assistant_calls.jsonl`，只保存时间、路由、工具名、校验状态、引用数量和耗时，不保存问题原文、CRM 行级记录或客户信息。设置 `RAG_BACKEND=keyword` 可强制使用轻量检索；默认优先使用 Chroma + `BAAI/bge-small-zh-v1.5`。

## 示例问题

- 哪些站长连续多天出现问题？
- 哪个省区的拍照不规范最多？
- 哪些站长同时涉及两类问题？
- CRM 导出需要哪些字段？
- 重点站长评分怎么组成？

## 业务边界

助手不自行判断虚假拜访，不查看照片，不替代 CRM 的质检 AI。所有问题类型来自 CRM 导出的“质检问题类型”；模型不能直接执行任意 SQL，也不能把真实 CRM 行级记录写入长期知识库。

公开 GitHub Pages 页面仍作为演示入口；完整 FastAPI 版本用于本地下载运行和面试演示。
