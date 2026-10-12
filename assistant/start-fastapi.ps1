$ErrorActionPreference = 'Stop'
$assistantRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $assistantRoot
if (-not (Test-Path 'server/.env')) {
  Copy-Item 'server/.env.example' 'server/.env'
  Write-Host 'Created server/.env. Please fill in DEEPSEEK_API_KEY and run again.'
}
Write-Host 'Installing or checking Python dependencies...'
py -3.12 -m pip install -r "backend/requirements.txt"
Write-Host 'Starting Visit Quality Assistant at http://localhost:8787'
py -3.12 -m uvicorn backend.main:app --host 127.0.0.1 --port 8787
