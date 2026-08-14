$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw '未找到 .venv，请先执行 scripts\start-windows.ps1'
}
& .\.venv\Scripts\python.exe -m playwright install chromium
& .\.venv\Scripts\python.exe .\scripts\auth_armory.py

