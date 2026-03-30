@echo off
setlocal

set "ROOT=D:\BT_NMS"
if not exist "%ROOT%\deploy\windows_host\run_bt_agent.bat" set "ROOT=%~dp0..\.."

set "SCRIPT_DIR=%ROOT%\deploy\windows_host"

echo [%date% %time%] starting bt_agent and sy_agent...

start "bt_agent" cmd /k ""%SCRIPT_DIR%\run_bt_agent.bat""
start "sy_agent" cmd /k ""%SCRIPT_DIR%\run_sy_agent.bat""

exit /b 0
