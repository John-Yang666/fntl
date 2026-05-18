param(
    [string]$OutputRoot = "",
    [string]$PythonLauncher = "py",
    [string[]]$PythonLauncherArgs = @("-3.12")
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$ArtifactsRoot = Join-Path $ScriptDir "artifacts"
$BuildRoot = Join-Path $ArtifactsRoot "build"
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $ArtifactsRoot "windows_agents"
}

$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$VenvPath = Join-Path $BuildRoot ".venv-protected"
$NuitkaRoot = Join-Path $BuildRoot "nuitka"
$PipInstallBaseArgs = @(
    "-m", "pip", "install",
    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
    "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
    "--timeout", "120",
    "--retries", "5"
)

function Invoke-PythonLauncher {
    param([string[]]$CommandArgs)
    & $PythonLauncher @PythonLauncherArgs @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python launcher failed: $PythonLauncher $($PythonLauncherArgs -join ' ') $($CommandArgs -join ' ')"
    }
}

function Invoke-PythonExe {
    param([string]$PythonExe, [string[]]$CommandArgs)
    & $PythonExe @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $PythonExe $($CommandArgs -join ' ')"
    }
}

function Build-NuitkaApp {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string[]]$ExtraArgs = @()
    )

    $ResolvedScript = (Resolve-Path (Join-Path $RepoRoot $ScriptPath)).Path
    $TargetDir = Join-Path $OutputRoot "apps\$Name"
    if (Test-Path $TargetDir) {
        Remove-Item $TargetDir -Recurse -Force
    }

    $Args = @(
        "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--output-dir=$NuitkaRoot",
        "--output-filename=$Name.exe"
    ) + $ExtraArgs + @($ResolvedScript)

    Invoke-PythonExe -PythonExe $PythonExe -CommandArgs $Args

    $DistDir = Join-Path $NuitkaRoot "$Name.dist"
    if (-not (Test-Path $DistDir)) {
        throw "Missing Nuitka output: $DistDir"
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $TargetDir) | Out-Null
    Move-Item $DistDir $TargetDir
}

New-Item -ItemType Directory -Force -Path $ArtifactsRoot, $BuildRoot, $NuitkaRoot, $OutputRoot | Out-Null

if (-not (Test-Path (Join-Path $VenvPath "Scripts\python.exe"))) {
    Invoke-PythonLauncher -CommandArgs @("-m", "venv", $VenvPath)
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
Invoke-PythonExe -PythonExe $PythonExe -CommandArgs ($PipInstallBaseArgs + @("--upgrade", "pip", "setuptools", "wheel"))
Invoke-PythonExe -PythonExe $PythonExe -CommandArgs ($PipInstallBaseArgs + @("nuitka", "ordered-set", "zstandard"))
Invoke-PythonExe -PythonExe $PythonExe -CommandArgs ($PipInstallBaseArgs + @("-r", (Join-Path $RepoRoot "bt_agent\requirements.txt"), "-r", (Join-Path $RepoRoot "bt_agent_serial\requirements.txt"), "-r", (Join-Path $RepoRoot "sy_agent\requirements.txt")))

$DiskAlarmAsset = Join-Path $RepoRoot "sy_agent\assets\disk_space_alarm.wav"
$SyAssetsDir = Join-Path $RepoRoot "sy_agent\assets"

Build-NuitkaApp -Name "bt_agent" -ScriptPath "bt_agent\bt_agent.py"
Build-NuitkaApp -Name "bt_agent_ui" -ScriptPath "bt_agent\bt_agent_ui.py" -ExtraArgs @(
    "--enable-plugin=pyside6",
    "--include-data-files=$DiskAlarmAsset=assets/disk_space_alarm.wav"
)
Build-NuitkaApp -Name "bt_agent_serial" -ScriptPath "bt_agent_serial\bt_agent_serial.py"
Build-NuitkaApp -Name "bt_agent_serial_ui" -ScriptPath "bt_agent_serial\bt_agent_serial_ui.py" -ExtraArgs @(
    "--enable-plugin=pyside6"
)
Build-NuitkaApp -Name "sy_agent" -ScriptPath "sy_agent\sy_agent.py"
Build-NuitkaApp -Name "sy_agent_ui" -ScriptPath "sy_agent\sy_agent_ui.py" -ExtraArgs @(
    "--enable-plugin=pyside6",
    "--include-data-dir=$SyAssetsDir=assets"
)
Build-NuitkaApp -Name "sy_agent_sub_ui" -ScriptPath "sy_agent\sy_agent_sub_ui.py" -ExtraArgs @(
    "--enable-plugin=pyside6",
    "--include-data-dir=$SyAssetsDir=assets"
)

$ScriptsOut = Join-Path $OutputRoot "scripts"
$TemplatesOut = Join-Path $OutputRoot "templates"
New-Item -ItemType Directory -Force -Path $ScriptsOut, $TemplatesOut | Out-Null

Copy-Item (Join-Path $ScriptDir "run_bt_agent.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_bt_agent_ui.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_bt_agent_serial.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_bt_agent_serial_ui.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_sy_agent.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_sy_agent_ui.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_sy_agent_sub_ui.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_agents.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_bt_agent_exe.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_bt_agent_serial_exe.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_sy_agent_exe.bat") $ScriptsOut -Force
Copy-Item (Join-Path $ScriptDir "run_agents_exe.bat") $ScriptsOut -Force
Copy-Item (Join-Path $RepoRoot "bt_agent\default_config.json") (Join-Path $TemplatesOut "bt_agent.config.json") -Force
Copy-Item (Join-Path $RepoRoot "bt_agent_serial\default_config.json") (Join-Path $TemplatesOut "bt_agent_serial.config.json") -Force
Copy-Item (Join-Path $RepoRoot "sy_agent\default_config.json") (Join-Path $TemplatesOut "sy_agent.config.json") -Force

Write-Host ""
Write-Host "Protected Windows bundle ready:" -ForegroundColor Green
Write-Host "  $OutputRoot"
