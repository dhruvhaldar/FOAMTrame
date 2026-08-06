$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 .\install.py @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python .\install.py @args
} else {
    throw "Python 3.10 or newer was not found. Install Python and enable it in PATH."
}

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

