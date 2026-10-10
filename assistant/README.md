# 虚假拜访问答助手

网页前端负责 Excel 上传和本地确定性分析；后端负责 DeepSeek 对话。本地 RAG 服务使用中文 Embedding 模型和 Chroma 检索业务知识。

## 本地运行

先启动 RAG 服务：

```powershell
py -3.12 -m uvicorn rag_service:app --host 127.0.0.1 --port 8790
```

再启动问答后端：

```powershell
node --env-file=server/.env server/server.mjs
```

打开 `http://localhost:8787`。

## 线上部署

使用 Docker 部署后端，并在平台环境变量中设置 `DEEPSEEK_API_KEY`。前端发布到 GitHub Pages 后，将 `window.QUALITY_ASSISTANT_API` 配置为后端公开地址。
