param(
    [string]$VenvPath = "",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$RunningOnWindows = ($PSVersionTable.PSEdition -eq "Desktop") -or ($PSVersionTable.ContainsKey("Platform") -and $PSVersionTable.Platform -eq "Win32NT")
if (-not $RunningOnWindows) {
    throw "This script must be run on Windows."
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$MainPy = Join-Path $RepoRoot "alarm_client\main.py"
$AudioFile = Join-Path $RepoRoot "frontend\public\audio\alert.mp3"
$IconFile = Join-Path $RepoRoot "frontend\public\favicon.ico"
$DistDir = Join-Path $RepoRoot "dist"
$BuildDir = Join-Path $RepoRoot "build\alarm_client_windows"
$SpecDir = Join-Path $RepoRoot "build"

if (-not (Test-Path $MainPy)) {
    throw "Cannot find entry point: $MainPy"
}
if (-not (Test-Path $AudioFile)) {
    throw "Cannot find alert audio file: $AudioFile"
}

if ([string]::IsNullOrWhiteSpace($VenvPath)) {
    $VenvPath = Join-Path $RepoRoot "venv"
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Cannot find Python in venv: $PythonExe. Create a Windows venv first or pass -VenvPath."
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $RepoRoot "alarm_client\requirements.txt")
if (-not $SkipInstall) {
    & $PythonExe -m pip install pyinstaller
}

$addData = "$AudioFile;frontend\public\audio"
$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "BT_SY_Alarm_Client",
    "--distpath", $DistDir,
    "--workpath", $BuildDir,
    "--specpath", $SpecDir,
    "--add-data", $addData,
    "--collect-all", "PySide6"
)

if (Test-Path $IconFile) {
    $pyinstallerArgs += @("--icon", $IconFile)
}

$pyinstallerArgs += $MainPy
& $PythonExe @pyinstallerArgs

$ExePath = Join-Path $DistDir "BT_SY_Alarm_Client.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build finished but exe was not found: $ExePath"
}

Write-Host "Built: $ExePath"
