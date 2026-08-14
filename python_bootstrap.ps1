param(
    [switch]$ForceBundled
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$PythonVersion = "3.12.13"
$ArchiveName = "cpython-3.12.13+20260807-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$ExpectedHash = "18bcc65b17921806b72cdc88bcf000bf67a2c99a8fc381fe1629f2b9ba56858d"
$VendorArchive = Join-Path $ProjectRoot "vendor\python\$PythonVersion\$ArchiveName"
$ToolsRoot = if ($env:FOAMTRAME_TOOLS_DIR) {
    [System.IO.Path]::GetFullPath($env:FOAMTRAME_TOOLS_DIR)
} else {
    Join-Path $ProjectRoot ".foamtrame-tools"
}
$InstallDir = Join-Path $ToolsRoot "python\$PythonVersion"
$BundledPython = Join-Path $InstallDir "python.exe"
$Probe = "import platform, sys; ok = platform.python_implementation() == 'CPython' and sys.version_info[:2] == (3, 12); print(sys.executable if ok else ''); raise SystemExit(0 if ok else 1)"

function Test-PythonCandidate {
    param(
        [string]$Command,
        [string[]]$Arguments = @()
    )

    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        return $null
    }
    $Output = & $Command @Arguments -c $Probe 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $Output) {
        return $null
    }
    return ([string]$Output).Trim()
}

if (-not $ForceBundled -and $env:FOAMTRAME_FORCE_BUNDLED_PYTHON -ne "1") {
    $Candidates = @(
        @{ Command = "python"; Arguments = @() },
        @{ Command = "python3.12"; Arguments = @() },
        @{ Command = "python3"; Arguments = @() },
        @{ Command = "py"; Arguments = @("-3.12") }
    )
    foreach ($Candidate in $Candidates) {
        $Resolved = Test-PythonCandidate @Candidate
        if ($Resolved) {
            Write-Output $Resolved
            exit 0
        }
    }
}

if (Test-Path -LiteralPath $BundledPython -PathType Leaf) {
    $Resolved = Test-PythonCandidate -Command $BundledPython
    if ($Resolved) {
        Write-Output $Resolved
        exit 0
    }
    throw "The locally bundled Python installation is invalid: $BundledPython"
}

$Architecture = if ($env:PROCESSOR_ARCHITEW6432) {
    $env:PROCESSOR_ARCHITEW6432
} else {
    $env:PROCESSOR_ARCHITECTURE
}
if ($Architecture -notin @("AMD64", "x86_64")) {
    throw "No bundled Python is available for Windows $Architecture. Install CPython 3.12 on PATH."
}
if (-not (Test-Path -LiteralPath $VendorArchive -PathType Leaf)) {
    throw "Bundled Python archive is missing: $VendorArchive"
}
$Sha256 = [System.Security.Cryptography.SHA256]::Create()
$ArchiveStream = [System.IO.File]::OpenRead($VendorArchive)
try {
    $HashBytes = $Sha256.ComputeHash($ArchiveStream)
} finally {
    $ArchiveStream.Dispose()
    $Sha256.Dispose()
}
$ActualHash = ([System.BitConverter]::ToString($HashBytes) -replace "-", "").ToLowerInvariant()
if ($ActualHash -ne $ExpectedHash) {
    throw "Bundled Python archive failed SHA-256 verification: $ArchiveName"
}
$TarCommand = Get-Command tar -ErrorAction SilentlyContinue
if (-not $TarCommand) {
    throw "The Windows tar utility is required to extract bundled Python."
}

$InstallParent = Split-Path -Parent $InstallDir
$TemporaryDir = Join-Path $InstallParent ".$PythonVersion.tmp-$PID"
New-Item -ItemType Directory -Path $TemporaryDir -Force | Out-Null
try {
    & $TarCommand.Source -xzf $VendorArchive -C $TemporaryDir --strip-components=1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not extract bundled Python from $ArchiveName"
    }
    $TemporaryPython = Join-Path $TemporaryDir "python.exe"
    $Resolved = Test-PythonCandidate -Command $TemporaryPython
    if (-not $Resolved) {
        throw "The extracted bundled Python executable failed validation."
    }
    Move-Item -LiteralPath $TemporaryDir -Destination $InstallDir
} finally {
    if (Test-Path -LiteralPath $TemporaryDir) {
        Remove-Item -LiteralPath $TemporaryDir -Recurse -Force
    }
}

Write-Output $BundledPython
