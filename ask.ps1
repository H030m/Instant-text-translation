$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONUTF8 = "1"
& (Join-Path $ProjectRoot ".venv\Scripts\python.exe") (Join-Path $ProjectRoot "ask.py") @args
