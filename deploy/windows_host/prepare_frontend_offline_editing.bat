@echo off
setlocal

set "ROOT=D:\BT_NMS"
if not exist "%ROOT%\frontend\package.json" set "ROOT=%~dp0..\.."

call :require_docker || exit /b 1

pushd "%ROOT%"

echo [INFO] Pulling Node build image...
docker pull node:22 || goto :fail

echo [INFO] Preparing offline npm cache in frontend\npm-cache ...
docker run --rm ^
  -v "%ROOT%\frontend:/app" ^
  -w /app ^
  node:22 ^
  sh -lc "npm config set registry https://registry.npmmirror.com && rm -rf npm-cache && npm ci --cache ./npm-cache --no-audit --no-fund" || goto :fail

echo [INFO] Done.
echo [INFO] You can now edit frontend source files offline and use build_and_apply_frontend_dist_offline.bat
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
