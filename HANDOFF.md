# 项目交接说明

更新日期：2026-10-19

## 项目目标

“拜访质量分析智能助手”面向省区运营同学。用户上传 CRM 已质检的拜访 Excel 后，可以用自然语言查询站长、省区、日期、客户、问题类型和统计次数，也可以查询评分规则、字段要求和通报口径。

核心原则是“大模型理解意图，程序计算事实”：模型负责选择 Agent、调用 Function、提取查询条件和解释结果；关键统计数字必须来自浏览器对当前 Excel 的确定性计算。

## 当前工作流

```text
用户问题
→ LangGraph Supervisor
→ data / knowledge / quality / publishing Agent
→ Function Calling 生成白名单计划
→ 浏览器执行当前 Excel 查询或后端执行知识检索
→ FastAPI 校验结果
→ 模型生成自然语言回答
→ 用户确认后才能发送飞书
```

当前 `/api/plan` 和 `/api/answer` 还是前后两个阶段；浏览器负责在中间执行本地 Excel 查询。

## 已完成进展

1. 四 Agent LangGraph 路由和严格 Function Calling。
2. Pydantic 校验 Agent 决策、查询计划、知识充分性、改写与重排结果。
3. 混合 RAG：关键词检索、向量检索、RRF、Rerank、相关性过滤。
4. 独立的知识资料充分性审查：审查模型只能依据检索片段输出 `is_sufficient` 和 `missing_information`；不得直接回答或使用自身知识补全。
5. 首次资料不足时，根据缺失信息改写查询并补充检索一次；二次审查仍不足则安全拒答，并明确告诉用户缺少什么资料。
6. Trace ID、白名单审计日志和各阶段可观测信息。
7. 脱敏滚动记忆与 SQLite 持久化：哈希会话键、ERP 落盘前移除、7 天 TTL。
8. 知识检索缓存：SHA256 键、10 分钟 TTL、LRU 128；不缓存 Excel 结果和回答。
9. 阻塞检索和 SQLite 操作通过线程卸载。
10. 8 条脱敏黄金评测案例，覆盖全部四个 Agent。
11. 分层评测：Agent、工具、参数、整体通过率、失败率和平均耗时。
12. 飞书 MCP 状态检查、发布预览和用户二次确认。

充分性审查的完整链路为：

```text
检索 → 重排与过滤 → 判断资料是否足以支持答案
├─ sufficient：生成回答
└─ insufficient：记录缺失信息 → 改写查询 → 补充检索 → 再审查
   ├─ sufficient：生成回答
   └─ insufficient：安全拒答
```

注意：相关性过滤解决“片段是否相关”，充分性审查解决“相关片段加起来是否足够回答”，两者不能互相替代。

截至本说明更新前，自动化测试基线为 `71 passed`；完整 8 条真实模型评测为 `8/8 passed`。近期提交已完成查询计划绑定、工具结果校验、待恢复工作流摘要持久化、单数排名归一化和泛称虚假安全边界加固。

## 关键文件

- `assistant/backend/main.py`：FastAPI、LangGraph、Agent、RAG、记忆、日志和接口。
- `assistant/backend/tools.py`：白名单工具执行与结果校验。
- `assistant/backend/feishu.py`：飞书 MCP 状态与发送封装。
- `assistant/backend/eval_cases.json`：黄金评测问题及标准结果。
- `assistant/backend/evaluation.py`：分层评分和聚合指标。
- `assistant/backend/run_evaluation.py`：真实模型评测命令。
- `assistant/backend/test_*.py`：自动化测试。
- `assistant/knowledge/`：只允许存放稳定规则资料，禁止写入真实 CRM 明细。

## 运行与验证

不得因为默认 Python 缺少依赖就判断项目无法运行。Windows 环境统一使用：

```powershell
py -0p
py -3.12 -m pip install -r assistant/backend/requirements.txt
py -3.12 -m pytest assistant/backend -q
```

启动服务：

```powershell
cd assistant
py -3.12 -m uvicorn backend.main:app --host 127.0.0.1 --port 8787
```

运行自然语言评测：

```powershell
py -3.12 -m assistant.backend.run_evaluation --limit 1
py -3.12 -m assistant.backend.run_evaluation
```

后端代码变化后，必须结束占用 8787 端口的旧进程、重新启动，并调用 `/api/health` 或新增接口进行运行时验证。刷新网页不等于重启后端。

## 不可破坏的业务边界

- 不允许模型自行判断虚假、查看照片或创造问题类型。
- 事实来源只能是 CRM 已识别的“质检问题类型”。
- “反馈内容无意义”不参与问题统计、候选、评分、排名或模型上下文。
- 真实 Excel 行级记录默认只在浏览器当前会话处理，不进入 RAG、日志或长期记忆。
- 模型不能直接计算关键数字、执行任意 SQL、修改 Excel 或绕过结果校验。
- 泛称“虚假、违规”不能自动映射为“疑似虚假上报异常”。
- 省区、日期、ERP、问题类型、指标和 Top N 必须进入结构化计划并接受校验。
- 飞书属于外部副作用，必须先预览并由用户明确确认；模型不能选择接收目标。

## 下一步

优先把查询计划和工具结果建立不可混淆的任务绑定，再逐步把工具结果校验和回答生成纳入同一个可暂停、恢复的 LangGraph：

```text
Supervisor → 专业 Agent → 查询计划 → 等待浏览器工具结果
→ 恢复任务 → 校验结果 → 回答生成 → 保存安全会话状态
```

第一小步建议增加 `workflow_id` 或等价签名，使 `/api/answer` 只能接收同一问题、同一计划产生的工具结果，防止 A 问题的结果被提交给 B 问题。不要一次性重写整个链路；每一步都应增加测试、运行冒烟评测并单独提交。

当前已完成上述第一步。后续优先推进多轮会话评测和可暂停/恢复 Graph 节点化，保持每次小改动、全量测试和真实模型评测。

已新增多轮真实评测：

```powershell
py -3.12 -m assistant.backend.conversation_eval
```

当前覆盖“广东 → 浙江”“修改日期”的连续追问，必须按完整的“规划 → 工具结果 → 回答 → 下一轮规划”链路执行；当前 3/3 轮通过。
