@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%..\apps\bt_agent_ui\bt_agent_ui.exe" (
  set "ROOT=%SCRIPT_DIR%.."
) else if exist "%SCRIPT_DIR%artifacts\windows_agents\apps\bt_agent_ui\bt_agent_ui.exe" (
  set "ROOT=%SCRIPT_DIR%artifacts\windows_agents"
) else (
  set "ROOT=%SCRIPT_DIR%..\..\artifacts\windows_agents"
)
set "BT_NMS_PROTECTED_HOME=%ROOT%"

echo [%date% %time%] starting bt_agent_ui and sy_agent_ui...

start "bt_agent_ui" cmd /k ""%SCRIPT_DIR%\run_bt_agent_ui.bat""
start "sy_agent_ui" cmd /k ""%SCRIPT_DIR%\run_sy_agent_ui.bat""

exit /b 0
