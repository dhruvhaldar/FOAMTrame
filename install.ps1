$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$PythonOutput = & .\python_bootstrap.ps1
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
$PythonExe = ([string]$PythonOutput).Trim()

& $PythonExe .\install.py @args

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
