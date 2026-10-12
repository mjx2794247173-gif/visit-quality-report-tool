$ErrorActionPreference = 'Stop'
$assistantRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $assistantRoot
if (-not (Test-Path 'server/.env')) {
  Copy-Item 'server/.env.example' 'server/.env'
  Write-Host '已创建 server/.env，请先填入 DEEPSEEK_API_KEY。'
}
if (-not (Test-Path 'backend/.venv-ready')) {
  py -3.12 -m pip install -r backend/requirements.txt
  New-Item 'backend/.venv-ready' -ItemType File | Out-Null
}
py -3.12 -m uvicorn backend.main:app --host 127.0.0.1 --port 8787
