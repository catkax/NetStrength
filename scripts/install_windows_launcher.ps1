param(
    [ValidateSet("auto", "script", "exe")]
    [string]$TargetType = "auto",
    [string]$ShortcutName = "NetStrength",
    [switch]$Desktop = $true,
    [switch]$StartMenu = $true,
    [string]$IconPath
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$scriptLauncher = Join-Path $projectRoot "NetStrength GUI.cmd"
$exeLauncherOneFile = Join-Path $projectRoot "dist\NetStrength.exe"
$exeLauncherOneDir = Join-Path $projectRoot "dist\NetStrength\NetStrength.exe"
$defaultIconPath = Join-Path $projectRoot "assets\NetStrength.ico"
if (-not $IconPath) {
    $IconPath = $defaultIconPath
}

$explicitIconProvided = $PSBoundParameters.ContainsKey("IconPath")

function Resolve-TargetPath {
    param(
        [Parameter(Mandatory = $true)][string]$RequestedType
    )

    if ($RequestedType -eq "exe") {
        if (Test-Path $exeLauncherOneFile) {
            return $exeLauncherOneFile
        }
        if (Test-Path $exeLauncherOneDir) {
            return $exeLauncherOneDir
        }
        throw "No launcher exe found. Build one first with scripts/build_slim_launcher_exe.ps1"
    }

    if ($RequestedType -eq "script") {
        if (-not (Test-Path $scriptLauncher)) {
            throw "Script launcher not found: $scriptLauncher"
        }
        return $scriptLauncher
    }

    if (Test-Path $exeLauncherOneFile) {
        return $exeLauncherOneFile
    }
    if (Test-Path $exeLauncherOneDir) {
        return $exeLauncherOneDir
    }
    if (-not (Test-Path $scriptLauncher)) {
        throw "Script launcher not found: $scriptLauncher"
    }
    return $scriptLauncher
}

function Resolve-ShortcutIcon {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$RequestedIcon
    )

    $targetIsExe = ([System.IO.Path]::GetExtension($Target)).ToLowerInvariant() -eq ".exe"

    if ($targetIsExe -and -not $explicitIconProvided) {
        # For EXE targets, use the icon embedded in the executable by default.
        return $Target
    }

    if ($RequestedIcon -and (Test-Path $RequestedIcon)) {
        return $RequestedIcon
    }

    if ($RequestedIcon -and -not (Test-Path $RequestedIcon)) {
        Write-Host "Requested icon was not found: $RequestedIcon"
    }

    if (Test-Path $defaultIconPath) {
        return $defaultIconPath
    }

    return $null
}

$targetPath = Resolve-TargetPath -RequestedType $TargetType
$iconFile = Resolve-ShortcutIcon -Target $targetPath -RequestedIcon $IconPath

$shell = New-Object -ComObject WScript.Shell

function New-Shortcut {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [string]$Icon,
        [string]$Description = "NetStrength GUI launcher"
    )

    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Description = $Description
    if ($Icon -and (Test-Path $Icon)) {
        $shortcut.IconLocation = "$Icon,0"
    }
    $shortcut.Save()
}

if ($Desktop) {
    $desktopDir = [Environment]::GetFolderPath("Desktop")
    $desktopLink = Join-Path $desktopDir "$ShortcutName.lnk"
    New-Shortcut -Path $desktopLink -Target $targetPath -WorkingDirectory $projectRoot -Icon $iconFile
    Write-Host "Desktop shortcut created: $desktopLink"
}

if ($StartMenu) {
    $startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $startMenuLink = Join-Path $startMenuDir "$ShortcutName.lnk"
    New-Shortcut -Path $startMenuLink -Target $targetPath -WorkingDirectory $projectRoot -Icon $iconFile
    Write-Host "Start menu shortcut created: $startMenuLink"
}

Write-Host "Launcher target: $targetPath"
if ($iconFile) {
    Write-Host "Shortcut icon: $iconFile"
} else {
    Write-Host "Shortcut icon: default (custom icon unavailable)"
}
