param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot

# --- Step 1: Convert PNG to ICO ---
Write-Host "=== Step 1: Converting logo PNG to ICO ==="

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
    $pythonArgsPrefix = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
    $pythonArgsPrefix = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
    $pythonArgsPrefix = @()
} else {
    throw "Python not found. Install Python 3 or create .venv first."
}

& $python @pythonArgsPrefix (Join-Path $PSScriptRoot "convert_logo_to_ico.py")

# --- Step 2: Build launcher EXE ---
Write-Host ""
Write-Host "=== Step 2: Building launcher EXE ==="

$buildScript = Join-Path $PSScriptRoot "build_slim_launcher_exe.ps1"
if ($OneFile) {
    & $buildScript -OneFile
} else {
    & $buildScript
}

# --- Step 3: Install shortcuts ---
Write-Host ""
Write-Host "=== Step 3: Installing shortcuts ==="

& (Join-Path $PSScriptRoot "install_windows_launcher.ps1")

Write-Host ""
Write-Host "Done! Icon, EXE, and shortcuts are all up to date."
