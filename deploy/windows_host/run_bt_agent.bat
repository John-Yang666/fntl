@echo off
setlocal

set "ROOT=D:\BT_NMS"
if not exist "%ROOT%\bt_agent\bt_agent.py" set "ROOT=%~dp0..\.."
pushd "%ROOT%"

if not exist "bt_agent\config.py" (
  echo [ERROR] Missing bt_agent\config.py.
  popd
  exit /b 1
)

call :resolve_python
if errorlevel 1 (
  popd
  exit /b 1
)

echo [INFO] Starting bt_agent from %CD% with %PYTHON_CMD%
%PYTHON_CMD% bt_agent\bt_agent.py
set "EXIT_CODE=%ERRORLEVEL%"

echo [INFO] bt_agent exited with code %EXIT_CODE%
popd
exit /b %EXIT_CODE%

:resolve_python
where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
  exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  exit /b 0
)

echo [ERROR] Python was not found in PATH. Install Python and enable py or python.
exit /b 1
