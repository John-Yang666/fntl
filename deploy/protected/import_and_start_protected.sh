#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TAR_PATH="${1:-${ROOT_DIR}/deploy/protected/artifacts/protected-images.tar}"
MODE="${2:-all}"

cd "${ROOT_DIR}"

docker load -i "${TAR_PATH}"

case "${MODE}" in
  bt)
    docker compose -f docker-compose-prod.yml up -d
    ;;
  sy)
    docker compose -f docker-compose-sy-prod.yml up -d
    ;;
  all)
    docker compose -f docker-compose-prod.yml up -d
    docker compose -f docker-compose-sy-prod.yml up -d
    ;;
  *)
    echo "Usage: $0 [tar-path] [bt|sy|all]" >&2
    exit 1
    ;;
esac
