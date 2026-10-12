@echo off
cd /d "%~dp0"
start "质量通报助手服务" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0start-fastapi.ps1"
timeout /t 4 /nobreak >nul
start "" "http://localhost:8787"
