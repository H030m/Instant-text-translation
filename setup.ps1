$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Set-Location -LiteralPath $ProjectRoot
$env:PYTHONUTF8 = "1"
$env:HF_HOME = Join-Path $ProjectRoot "cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = Join-Path $ProjectRoot "models"
$env:XDG_CACHE_HOME = Join-Path $ProjectRoot "cache"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Host "[1/3] 建立專案內 Python 虛擬環境 .venv"
    py -3.13 -m venv (Join-Path $ProjectRoot ".venv")
}

Write-Host "[2/3] 安裝固定版本套件"
& $PythonExe -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/3] 下載並驗證 small 模型"
& $PythonExe (Join-Path $ProjectRoot "run.py") --model small --download-only
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "完成。執行 .\start.ps1 即可開始直播轉文字。"
