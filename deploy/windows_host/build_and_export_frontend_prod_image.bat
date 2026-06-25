@echo off
setlocal

set "ROOT=D:\BT_NMS"
if not exist "%ROOT%\frontend\Dockerfile.prod" set "ROOT=%~dp0..\.."

set "ARTIFACT_DIR=%ROOT%\deploy\windows_host\artifacts"
set "IMAGE_NAME=my_vue:prod"
set "TAR_PATH=%ARTIFACT_DIR%\my_vue_prod.tar"
set "BT_PORT=8000"
set "SY_PORT=8001"

call :require_docker || exit /b 1

if not exist "%ARTIFACT_DIR%" mkdir "%ARTIFACT_DIR%"

pushd "%ROOT%"

echo [INFO] Pulling required base images...
docker pull node:22@sha256:e0d149b4727ac0c20d9774e801e423d7a946a0bffced886f42cfe9cd3c67820a || goto :fail
docker pull nginxinc/nginx-unprivileged:1.31.2-alpine3.23@sha256:054e14f543eb688809d59ec2ad1644d1a61678e247c87a318ad605977eb37eaf || goto :fail

echo [INFO] Building %IMAGE_NAME% ...
docker build -t %IMAGE_NAME% -f frontend/Dockerfile.prod --build-arg VITE_BT_BACKEND_PORT=%BT_PORT% --build-arg VITE_SY_BACKEND_PORT=%SY_PORT% frontend || goto :fail

echo [INFO] Exporting %IMAGE_NAME% to %TAR_PATH% ...
docker save -o "%TAR_PATH%" %IMAGE_NAME% || goto :fail

echo [INFO] Done.
echo [INFO] Artifact: %TAR_PATH%
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
