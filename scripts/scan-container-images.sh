#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRIVY_IMAGE="${TRIVY_IMAGE:-aquasec/trivy:0.58.2@sha256:665030f4d33a82c1e8d9d5e0453365842236723c1ee5cc3becca698268e66a56}"
TRIVY_CACHE_DIR="${TRIVY_CACHE_DIR:-${ROOT_DIR}/.trivy-cache}"
TRIVY_SEVERITY="${TRIVY_SEVERITY:-HIGH,CRITICAL}"
TRIVY_IGNORE_UNFIXED="${TRIVY_IGNORE_UNFIXED:-1}"
TRIVY_TIMEOUT="${TRIVY_TIMEOUT:-15m}"
DOCKER_SOCKET="${DOCKER_HOST_SOCKET:-/var/run/docker.sock}"

usage() {
  cat <<'EOF'
Usage:
  scripts/scan-container-images.sh IMAGE [IMAGE...]

Scans container images with Trivy. The default policy fails on HIGH/CRITICAL
vulnerabilities that have a fixed version available.

Environment:
  TRIVY_IMAGE            Scanner image. Defaults to pinned aquasec/trivy:0.58.2 digest.
  TRIVY_SEVERITY         Severity list. Defaults to HIGH,CRITICAL.
  TRIVY_IGNORE_UNFIXED   1 to ignore vulnerabilities without a fixed version. Defaults to 1.
  TRIVY_CACHE_DIR        Cache directory. Defaults to .trivy-cache under repo root.
  TRIVY_TIMEOUT          Scanner timeout. Defaults to 15m. Set to 0 for a 168h wait.
  DOCKER_HOST_SOCKET     Docker socket to mount into Trivy. Defaults to /var/run/docker.sock.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if (( "$#" == 0 )); then
  usage >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for container image scanning." >&2
  exit 2
fi

mkdir -p "${TRIVY_CACHE_DIR}"

trivy_args=(
  image
  --scanners vuln
  --severity "${TRIVY_SEVERITY}"
  --exit-code 1
  --no-progress
)

if [[ "${TRIVY_TIMEOUT}" == "0" ]]; then
  trivy_args+=(--timeout 168h)
elif [[ -n "${TRIVY_TIMEOUT}" ]]; then
  trivy_args+=(--timeout "${TRIVY_TIMEOUT}")
fi

if [[ "${TRIVY_IGNORE_UNFIXED}" == "1" ]]; then
  trivy_args+=(--ignore-unfixed)
fi

status=0
for image in "$@"; do
  printf '\n==> Scanning %s\n' "${image}"
  if ! docker run --rm \
    -v "${DOCKER_SOCKET}:/var/run/docker.sock" \
    -v "${TRIVY_CACHE_DIR}:/root/.cache/trivy" \
    "${TRIVY_IMAGE}" \
    "${trivy_args[@]}" \
    "${image}"; then
    status=1
  fi
done

exit "${status}"
