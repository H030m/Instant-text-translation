param(
    [Parameter(Position = 0)]
    [string]$Source = "https://www.youtube.com/live/0Hb5laOEUVs",
    [string]$Model = "small",
    [string]$Language = "zh",
    [double]$ChunkSeconds = 5.0,
    [double]$RefreshSeconds = 20.0,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "尚未完成安裝。請先在此目錄執行：.\setup.ps1"
}

Set-Location -LiteralPath $ProjectRoot
$env:PYTHONUTF8 = "1"
$env:HF_HOME = Join-Path $ProjectRoot "cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = Join-Path $ProjectRoot "models"
$env:XDG_CACHE_HOME = Join-Path $ProjectRoot "cache"

$RunArgs = @(
    (Join-Path $ProjectRoot "run.py"), $Source,
    "--model", $Model, "--language", $Language,
    "--chunk-seconds", $ChunkSeconds,
    "--refresh-seconds", $RefreshSeconds
)
if ($Output) {
    $RunArgs += @("--output", $Output)
}
& $PythonExe @RunArgs
exit $LASTEXITCODE
