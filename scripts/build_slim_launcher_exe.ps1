param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherScript = Join-Path $PSScriptRoot "netstrength_launcher.py"

if (-not (Test-Path $launcherScript)) {
    throw "Launcher script not found: $launcherScript"
}

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
    throw "Python launcher not found. Install Python 3 or create .venv first."
}

Write-Host "Using Python launcher: $python"

& $python @pythonArgsPrefix -m pip install --upgrade pyinstaller

$distDir = Join-Path $projectRoot "dist"
$buildDir = Join-Path $projectRoot "build\launcher"
$specDir = Join-Path $projectRoot "build\spec"
$iconPath = Join-Path $projectRoot "assets\NetStrength.ico"

$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "NetStrength",
    "--distpath", $distDir,
    "--workpath", $buildDir,
    "--specpath", $specDir,
    $launcherScript
)

if (Test-Path $iconPath) {
    $pyInstallerArgs += @("--icon", $iconPath)
}

if ($OneFile) {
    $pyInstallerArgs += "--onefile"
} else {
    $pyInstallerArgs += "--onedir"
}

& $python @pythonArgsPrefix @pyInstallerArgs

if ($OneFile) {
    $exePath = Join-Path $distDir "NetStrength.exe"
} else {
    $exePath = Join-Path $distDir "NetStrength\NetStrength.exe"
}

if (Test-Path $exePath) {
    Write-Host "Built launcher executable: $exePath"
} else {
    throw "Build finished but executable was not found."
}
