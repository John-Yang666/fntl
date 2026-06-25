#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/deploy/protected/artifacts"
OUTPUT_TAR="${1:-${ARTIFACT_DIR}/protected-images.tar}"

mkdir -p "${ARTIFACT_DIR}"

cd "${ROOT_DIR}"

docker build -t my_django:v5.2.15-py3.14-prod -f backend/Dockerfile.prod backend
docker build -t my_django:v5.2.15-py3.14-sy-prod -f sy_backend/Dockerfile.prod sy_backend
docker build -t my_vue:prod -f frontend/Dockerfile.prod \
  --build-arg VITE_BT_BACKEND_PORT=8000 \
  --build-arg VITE_SY_BACKEND_PORT=8001 \
  frontend
docker build -t bt_nms_postgres:16.14-bookworm-secure -f deploy/postgres/Dockerfile deploy/postgres
docker build -t bt_nms_flower:2.0.1-py3.14-slim -f deploy/flower/Dockerfile deploy/flower

docker pull redis:7.4.9-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99
docker pull python:3.14-slim@sha256:44dd04494ee8f3b538294360e7c4b3acb87c8268e4d0a4828a6500b1eff50061
docker pull nginxinc/nginx-unprivileged:1.31.2-alpine3.23@sha256:054e14f543eb688809d59ec2ad1644d1a61678e247c87a318ad605977eb37eaf

docker save \
  -o "${OUTPUT_TAR}" \
  my_django:v5.2.15-py3.14-prod \
  my_django:v5.2.15-py3.14-sy-prod \
  my_vue:prod \
  bt_nms_postgres:16.14-bookworm-secure \
  bt_nms_flower:2.0.1-py3.14-slim \
  redis:7.4.9-alpine \
  python:3.14-slim \
  nginxinc/nginx-unprivileged:1.31.2-alpine3.23

echo "Wrote ${OUTPUT_TAR}"
