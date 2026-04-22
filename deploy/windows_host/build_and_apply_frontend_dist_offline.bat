@echo off
setlocal

set "ROOT=D:\BT_NMS"
if not exist "%ROOT%\frontend\package.json" set "ROOT=%~dp0..\.."

call :require_docker || exit /b 1

docker image inspect node:22 >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Missing local image node:22. Run prepare_frontend_offline_editing.bat once while online.
  call :hold
  exit /b 1
)

if not exist "%ROOT%\frontend\npm-cache\_cacache" (
  echo [ERROR] Missing frontend\npm-cache\_cacache.
  echo [ERROR] Run prepare_frontend_offline_editing.bat once while online.
  call :hold
  exit /b 1
)

pushd "%ROOT%"

echo [INFO] Building frontend dist offline from local source...
echo [INFO] Maintenance/dev workflow only. Protected deploys should ship dist or image artifacts, not source.
docker run --rm --network none ^
  -v "%ROOT%\frontend:/app" ^
  -w /app ^
  node:22 ^
  sh -lc "rm -rf dist && npm ci --offline --cache ./npm-cache --no-audit --no-fund && npm run build && test -f dist/index.html" || goto :fail

echo [INFO] Recreating vue service with local dist mount...
docker compose -f docker-compose-prod.yml -f docker-compose-prod.frontend-local.yml up -d --no-deps --force-recreate vue || goto :fail

echo [INFO] Done.
echo [INFO] Frontend is now serving host dist from frontend\dist
echo [INFO] Hard refresh the browser with Ctrl+F5 after each frontend update.
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
