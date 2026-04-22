#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/deploy/protected/artifacts"
OUTPUT_TAR="${1:-${ARTIFACT_DIR}/protected-images.tar}"

mkdir -p "${ARTIFACT_DIR}"

cd "${ROOT_DIR}"

docker build -t my_django:v5.0.6-prod -f backend/Dockerfile.prod backend
docker build -t my_django:v5.0.6-sy-prod -f sy_backend/Dockerfile.prod sy_backend
docker build -t my_vue:prod -f frontend/Dockerfile.prod \
  --build-arg VITE_BT_BACKEND_PORT=8000 \
  --build-arg VITE_SY_BACKEND_PORT=8001 \
  frontend

docker pull redis:7.4.1
docker pull postgres:16.3
docker pull nginx:1.27-alpine

docker save \
  -o "${OUTPUT_TAR}" \
  my_django:v5.0.6-prod \
  my_django:v5.0.6-sy-prod \
  my_vue:prod \
  redis:7.4.1 \
  postgres:16.3 \
  nginx:1.27-alpine

echo "Wrote ${OUTPUT_TAR}"
