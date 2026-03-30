@echo off
setlocal

set "ROOT=D:\BT_NMS"
if not exist "%ROOT%\docker-compose-prod.yml" set "ROOT=%~dp0..\.."

set "ARTIFACT_DIR=%ROOT%\deploy\windows_host\artifacts"
set "TAR_PATH=%ARTIFACT_DIR%\my_vue_prod.tar"

if not "%~1"=="" set "TAR_PATH=%~1"

call :require_docker || exit /b 1

if not exist "%TAR_PATH%" (
  echo [ERROR] Frontend image tar not found: %TAR_PATH%
  call :hold
  exit /b 1
)

pushd "%ROOT%"

echo [INFO] Loading image from %TAR_PATH% ...
docker load -i "%TAR_PATH%" || goto :fail

echo [INFO] Recreating vue service ...
docker compose -f docker-compose-prod.yml up -d --no-deps --force-recreate vue || goto :fail

echo [INFO] Done.
popd
call :hold
exit /b 0

:fail
set "EXIT_CODE=%ERRORLEVEL%"
echo [ERROR] Failed with exit code %EXIT_CODE%.
popd
call :hold
exit /b %EXIT_CODE%

:require_docker
where docker >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Docker was not found in PATH.
  call :hold
  exit /b 1
)
exit /b 0

:hold
echo.
pause
exit /b 0
