# Agent 开发说明

开始修改前，先阅读 `README.md`、`assistant/README.md` 和 `HANDOFF.md`。

## 环境与测试

- 不要使用默认 `python`，它可能指向非项目运行时。
- 先运行 `py -0p`，确认 Python 3.12 可用。
- 安装依赖：`py -3.12 -m pip install -r assistant/backend/requirements.txt`
- 运行测试：`py -3.12 -m pytest assistant/backend -q`
- 当前测试基线：66 个测试通过。

## 修改要求

- 每次只完成一个可验证的小改动，并增加相应测试。
- 不得提交真实 CRM 数据、密钥、群 ID、SQLite 会话文件或调用日志。
- 大模型负责理解和解释；统计数字由白名单程序计算并校验。
- 不得以关键词硬编码替代模型的自然语言意图理解，但确定性安全校验可以拒绝越权或不一致参数。
- 不得把“虚假”自动等同于“疑似虚假上报异常”。
- “反馈内容无意义”必须始终排除。
- 向飞书发送前必须有发布预览和用户确认。

## 后端运行时验证

修改 `assistant/backend/` 后，磁盘文件更新并不表示正在运行的 Uvicorn 已更新。必须：

1. 找到并结束占用 8787 端口的旧 Python 进程。
2. 在 `assistant` 目录使用 Python 3.12 重启 Uvicorn。
3. 调用 `/api/health` 和相关接口确认新代码已加载。
4. 运行全部 pytest；涉及模型规划时再运行 `run_evaluation --limit 1`。

## Git

保留用户已有改动，不使用破坏性重置。验证通过后提交到当前分支并同步远端；在交付信息中说明测试结果和提交号。
