@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "APP_DIR=bt_agent_ui"
set "APP_EXE=bt_agent_ui.exe"
set "APP_LABEL=bt_agent_ui"

call :resolve_root
if errorlevel 1 exit /b 1

if not defined BT_AGENT_UI_RESTART_STABLE_RUN_SEC set "BT_AGENT_UI_RESTART_STABLE_RUN_SEC=60"
if not defined BT_AGENT_UI_RESTART_BACKOFF_MAX_SEC set "BT_AGENT_UI_RESTART_BACKOFF_MAX_SEC=30"
set /a RESTART_STREAK=0

set "BT_NMS_PROTECTED_HOME=%ROOT%"
set "APP_PATH=%ROOT%\apps\%APP_DIR%\%APP_EXE%"
pushd "%ROOT%"

echo [INFO] Starting %APP_LABEL% from %APP_PATH%
echo [INFO] Restart loop enabled. Set BT_AGENT_UI_RUN_ONCE=1 to disable.
echo [INFO] Immediate restart on first failure, with backoff for short consecutive failures.

:run_loop
call :now_epoch RUN_START_EPOCH
"%APP_PATH%"
set "EXIT_CODE=%ERRORLEVEL%"
call :now_epoch RUN_END_EPOCH
set /a RUN_UPTIME_SEC=RUN_END_EPOCH-RUN_START_EPOCH

if /i "%BT_AGENT_UI_RUN_ONCE%"=="1" (
  echo [INFO] %APP_LABEL% exited with code %EXIT_CODE%
  popd
  exit /b %EXIT_CODE%
)

echo [WARN] %APP_LABEL% exited with code %EXIT_CODE%
if !RUN_UPTIME_SEC! GEQ %BT_AGENT_UI_RESTART_STABLE_RUN_SEC% (
  set /a RESTART_STREAK=0
) else (
  set /a RESTART_STREAK+=1
)
call :calc_backoff !RESTART_STREAK! %BT_AGENT_UI_RESTART_BACKOFF_MAX_SEC% RESTART_DELAY_SEC
if !RUN_UPTIME_SEC! GEQ %BT_AGENT_UI_RESTART_STABLE_RUN_SEC% (
  echo [WARN] %APP_LABEL% was up for !RUN_UPTIME_SEC!s, treating this as a stable run.
)
if !RESTART_DELAY_SEC! GTR 0 (
  echo [WARN] Restarting %APP_LABEL% in !RESTART_DELAY_SEC!s after !RESTART_STREAK! consecutive short failures. Close this window to stop.
  timeout /t !RESTART_DELAY_SEC! >nul
) else (
  echo [WARN] Restarting %APP_LABEL% immediately. Close this window to stop.
)
goto :run_loop

:resolve_root
if defined BT_NMS_PROTECTED_HOME if exist "%BT_NMS_PROTECTED_HOME%\apps\%APP_DIR%\%APP_EXE%" (
  set "ROOT=%BT_NMS_PROTECTED_HOME%"
  exit /b 0
)
if exist "%~dp0..\apps\%APP_DIR%\%APP_EXE%" (
  set "ROOT=%~dp0.."
  exit /b 0
)
if exist "%~dp0artifacts\windows_agents\apps\%APP_DIR%\%APP_EXE%" (
  set "ROOT=%~dp0artifacts\windows_agents"
  exit /b 0
)
if exist "%~dp0..\..\artifacts\windows_agents\apps\%APP_DIR%\%APP_EXE%" (
  set "ROOT=%~dp0..\..\artifacts\windows_agents"
  exit /b 0
)
echo [ERROR] Missing %APP_DIR%\%APP_EXE%. Build the protected bundle first.
exit /b 1

:calc_backoff
setlocal
set /a "streak=%~1"
set /a "cap=%~2"
set /a "delay=0"
if %~1 GTR 1 (
  set /a "shift=streak-2"
  set /a "delay=1 << shift"
)
if !delay! GTR !cap! set /a "delay=cap"
endlocal & set "%~3=%delay%"
exit /b 0

:now_epoch
for /f %%I in ('powershell -NoProfile -Command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "%~1=%%I"
exit /b 0
