#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${SY_TEST_AGENT_COMPOSE_FILE:-}"
BASE_URL="${SY_TEST_AGENT_BASE_URL:-}"
HTTP_TRANSPORT="${SY_TEST_AGENT_HTTP_TRANSPORT:-}"
USERNAME="${SY_TEST_AGENT_USERNAME:-admin}"
PASSWORD="${SY_TEST_AGENT_PASSWORD:-admin}"
RECEIVER_CACHE_WAIT="${SY_TEST_AGENT_RECEIVER_CACHE_WAIT:-}"

compose_has_running_service() {
  local compose_file="$1"
  local service="$2"
  (cd "$ROOT_DIR" && docker compose -f "$compose_file" ps --status running --services 2>/dev/null | grep -Fxq "$service")
}

select_stack_defaults() {
  if [[ -z "$COMPOSE_FILE" ]]; then
    if compose_has_running_service docker-compose-sy.yml web; then
      COMPOSE_FILE="docker-compose-sy.yml"
    elif compose_has_running_service docker-compose-sy-prod.yml web; then
      COMPOSE_FILE="docker-compose-sy-prod.yml"
    else
      COMPOSE_FILE="docker-compose-sy.yml"
    fi
  fi

  if [[ -z "$HTTP_TRANSPORT" ]]; then
    if [[ "$COMPOSE_FILE" == *prod* ]]; then
      HTTP_TRANSPORT="compose"
    else
      HTTP_TRANSPORT="host"
    fi
  fi

  if [[ -z "$BASE_URL" ]]; then
    if [[ "$HTTP_TRANSPORT" == "compose" ]]; then
      BASE_URL="http://127.0.0.1:8000"
    else
      BASE_URL="http://127.0.0.1:8001"
    fi
  fi

  if [[ -z "$RECEIVER_CACHE_WAIT" ]]; then
    if [[ "$COMPOSE_FILE" == *prod* ]]; then
      RECEIVER_CACHE_WAIT="65"
    else
      RECEIVER_CACHE_WAIT="0"
    fi
  fi
}

require_running_service() {
  local service="$1"
  if ! (cd "$ROOT_DIR" && docker compose -f "$COMPOSE_FILE" ps --status running --services | grep -Fxq "$service"); then
    printf 'Required SY service is not running: %s\n' "$service" >&2
    printf 'Start the SY Docker stack first; this script does not run docker compose up.\n' >&2
    exit 2
  fi
}

if ! command -v docker >/dev/null 2>&1; then
  printf 'docker is required.\n' >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  printf 'python3 is required.\n' >&2
  exit 2
fi

select_stack_defaults

require_running_service web
require_running_service redis_stream
require_running_service sy_receiver
require_running_service summarize_alarms_container

(cd "$ROOT_DIR" && docker compose -f "$COMPOSE_FILE" exec -T redis_stream redis-cli ping >/dev/null)

if [[ "$HTTP_TRANSPORT" == "compose" ]]; then
  LOGIN_CMD=(docker compose -f "$COMPOSE_FILE" exec -T web python - "$BASE_URL" "$USERNAME" "$PASSWORD")
else
  LOGIN_CMD=(python3 - "$BASE_URL" "$USERNAME" "$PASSWORD")
fi

(cd "$ROOT_DIR" && "${LOGIN_CMD[@]}" <<'PY')
import json
import sys
from urllib import request

base_url = sys.argv[1].rstrip("/")
payload = json.dumps({"username": sys.argv[2], "password": sys.argv[3]}).encode()
req = request.Request(base_url + "/api/token/", data=payload, method="POST")
req.add_header("content-type", "application/json")
with request.urlopen(req, timeout=10) as response:
    data = json.loads(response.read().decode())
if "access" not in data:
    raise SystemExit("SY HTTP login did not return an access token")
PY

cd "$ROOT_DIR"
python3 -m sy_test_agent \
  --base-url "$BASE_URL" \
  --compose-file "$COMPOSE_FILE" \
  --http-transport "$HTTP_TRANSPORT" \
  --receiver-cache-wait "$RECEIVER_CACHE_WAIT" \
  --username "$USERNAME" \
  --password "$PASSWORD" \
  "$@"
