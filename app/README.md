# 拜访质量分析助手 Windows App

本 App 是公开飞书版桌面客户端。开发模式会自动启动本地 FastAPI 服务，并在固定窗口中打开助手页面。

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

## 无需 Visual Studio 的快速构建

如果电脑没有 C++ Build Tools，可以使用 Python WebView 版本：

```powershell
py -m pip install pywebview pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name VisitQualityAssistant launcher.py
```

生成的 `dist/VisitQualityAssistant.exe` 即为 Windows App。
