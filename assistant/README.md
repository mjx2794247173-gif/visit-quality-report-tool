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

## 本地运行（Windows，新手操作）

下面的步骤只需要第一次配置一次。运行过程中不要把 API Key 发到聊天群或提交到 GitHub。

### 第一步：下载项目

如果电脑安装了 Git，在 PowerShell 中执行：

```powershell
git clone https://github.com/mjx2794247173-gif/visit-quality-report-tool.git
cd visit-quality-report-tool\assistant
```

如果没有安装 Git，也可以在 GitHub 页面点击 **Code → Download ZIP**，解压后进入仓库中的 `assistant` 文件夹。

### 第二步：确认 Python

在当前 PowerShell 窗口执行：

```powershell
py -3.12 --version
```

看到 `Python 3.12.x` 就可以继续。如果提示找不到命令，需要先安装 Python 3.12，并在安装时勾选 **Add Python to PATH**。

### 第三步：创建并填写 API 配置

确保 PowerShell 当前目录是项目的 `assistant` 文件夹。可以执行：

```powershell
Get-Location
Test-Path .\server
```

第二条命令返回 `True` 才是正确目录。

创建配置文件：

```powershell
Copy-Item .\server\.env.example .\server\.env
```

用记事本打开配置文件：

```powershell
notepad .\server\.env
```

把这一行改成自己的 DeepSeek Key：

```env
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
```

保存后关闭记事本。不要在 PowerShell 中直接输入 `server/.env`，它是文件路径，不是可执行命令。

### 第四步：启动助手

在 `assistant` 目录中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start-fastapi.ps1
```

第一次启动会自动检查并安装 FastAPI、LangGraph、Chroma 和中文 Embedding 依赖，可能需要几分钟。看到下面的提示，说明后端已经启动：

```text
Uvicorn running on http://127.0.0.1:8787
```

保持这个 PowerShell 窗口打开，不要关闭它。

### 第五步：打开网页并测试

浏览器打开：

<http://localhost:8787>

点击“使用示例数据”，然后提问：

```text
哪些站长问题最多？
```

也可以上传 `sample_data/crm_visit_quality_demo.csv`。如果返回回答，说明网页、FastAPI、Function Calling 和本地分析链路已经启动成功。

### 常见问题

- **提示路径不存在**：先执行 `cd` 进入 `assistant` 文件夹，再执行后续命令。
- **PowerShell 不允许运行脚本**：执行 `Set-ExecutionPolicy -Scope Process Bypass`，只对当前窗口生效。
- **端口被占用**：关闭已经运行的助手窗口，或结束占用 `8787` 端口的进程后再启动。
- **健康检查**：浏览器打开 <http://localhost:8787/api/health>，看到 `"ok": true` 即表示 FastAPI 正常。
- **没有 API Key**：本地 Excel 解析仍可用，但 DeepSeek 问答无法运行；检查 `server/.env` 是否填写正确。
- **首次 RAG 较慢**：首次使用可能下载中文 Embedding 模型；网络受限时会自动回退关键词检索。

停止服务时，在运行 Uvicorn 的 PowerShell 窗口按 `Ctrl+C` 即可。

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
