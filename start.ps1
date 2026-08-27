$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    & $VenvPython .\run.py @args
    exit $LASTEXITCODE
}

$PythonOutput = & .\python_bootstrap.ps1
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
$PythonExe = ([string]$PythonOutput).Trim()

$UvOutput = & $PythonExe .\uv_bootstrap.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
$UvExe = ([string]$UvOutput).Trim()

& $UvExe run --quiet --locked --no-dev python .\run.py @args
exit $LASTEXITCODE
