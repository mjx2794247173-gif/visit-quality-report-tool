# 拜访质量分析助手 Windows App

本 App 基于 2026-10-26 本地京ME版构建。开发模式会自动启动本地 FastAPI 服务，并在固定窗口中打开助手页面。

## 开发运行

```powershell
npm install
npm run tauri dev
```

## 构建安装包

需要 Windows Visual Studio Build Tools，并勾选“使用 C++ 的桌面开发”。

```powershell
npm run tauri build
```

安装包会生成在 `src-tauri/target/release/bundle/`。
