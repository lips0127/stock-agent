#Requires -Version 7.0

[CmdletBinding()]
param(
    [string]$PythonExecutable
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$exitCode = 0

function Resolve-PythonExecutable {
    param(
        [string]$RequestedPython,
        [string]$RepositoryRoot
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedPython)) {
        if (Test-Path -LiteralPath $RequestedPython -PathType Leaf) {
            return (Resolve-Path -LiteralPath $RequestedPython).Path
        }

        $requestedCommand = Get-Command $RequestedPython -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $requestedCommand) {
            return $requestedCommand.Source
        }

        throw "Python executable was not found: $RequestedPython"
    }

    if (-not [string]::IsNullOrWhiteSpace($env:VIRTUAL_ENV)) {
        $activeVenvPython = Join-Path $env:VIRTUAL_ENV "Scripts/python.exe"
        if (Test-Path -LiteralPath $activeVenvPython -PathType Leaf) {
            return (Resolve-Path -LiteralPath $activeVenvPython).Path
        }
    }

    foreach ($relativePath in @(
        ".venv/Scripts/python.exe",
        "venv/Scripts/python.exe",
        "venv_new/Scripts/python.exe"
    )) {
        $candidate = Join-Path $RepositoryRoot $relativePath
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $pathPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $pathPython) {
        throw "No Python executable was found in VIRTUAL_ENV, repository virtual environments, or PATH."
    }

    return $pathPython.Source
}

$pythonExecutable = Resolve-PythonExecutable -RequestedPython $PythonExecutable -RepositoryRoot $repoRoot
Write-Host "Using Python executable: $pythonExecutable"

Push-Location -LiteralPath $repoRoot
try {
    & $pythonExecutable -m pytest tests -q -p no:cacheprovider
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Push-Location -LiteralPath (Join-Path $repoRoot "frontend")
        try {
            & npm run build
            $exitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
    }

    if ($exitCode -eq 0) {
        & git diff --check
        $exitCode = $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

exit $exitCode
