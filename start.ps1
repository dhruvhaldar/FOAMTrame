$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$PythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "FOAMTrame is not installed. Run .\install.ps1 first."
}

& $PythonExe .\run.py @args
exit $LASTEXITCODE

