#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_TEST_MODE="${FNTL_BACKEND_TEST_MODE:-docker}"

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="$PYTHON"
elif [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN="$(command -v python)"
fi

run_step() {
  local title="$1"
  local dir="$2"
  shift 2
  printf '\n==> %s\n' "$title"
  (cd "$dir" && "$@")
}

ensure_docker_compose() {
  if ! command -v docker >/dev/null 2>&1; then
    printf 'docker is required when FNTL_BACKEND_TEST_MODE=docker.\n' >&2
    exit 2
  fi
  if ! docker compose version >/dev/null 2>&1; then
    printf 'docker compose is required when FNTL_BACKEND_TEST_MODE=docker.\n' >&2
    exit 2
  fi
}

service_in_list() {
  local needle="$1"
  local services="${2:-}"
  local item
  while IFS= read -r item; do
    if [[ "$item" == "$needle" ]]; then
      return 0
    fi
  done <<< "$services"
  return 1
}

compose_service_running() {
  local compose_file="$1"
  local service="$2"
  (cd "$ROOT_DIR" && docker compose -f "$compose_file" ps --status running --services | grep -Fxq "$service")
}

stop_services_started_by_test() {
  local compose_file="$1"
  local before_services="${2:-}"
  local services_to_stop=()
  local service

  for service in db redis redis_stream; do
    if ! service_in_list "$service" "$before_services" && compose_service_running "$compose_file" "$service"; then
      services_to_stop+=("$service")
    fi
  done

  if (( ${#services_to_stop[@]} > 0 )); then
    (cd "$ROOT_DIR" && docker compose -f "$compose_file" stop "${services_to_stop[@]}")
  fi
}

run_docker_backend_step() {
  local title="$1"
  local compose_file="$2"
  local before_services
  local test_status

  printf '\n==> %s\n' "$title"
  before_services="$((cd "$ROOT_DIR" && docker compose -f "$compose_file" ps --status running --services) 2>/dev/null || true)"

  set +e
  (cd "$ROOT_DIR" && docker compose -f "$compose_file" run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py test myapp -v 2)
  test_status=$?
  set -e

  stop_services_started_by_test "$compose_file" "$before_services"
  return "$test_status"
}

run_backend_steps() {
  case "$BACKEND_TEST_MODE" in
    docker)
      ensure_docker_compose
      run_docker_backend_step "BT Django backend (Docker PostgreSQL)" "docker-compose.yml"
      run_docker_backend_step "SY Django backend (Docker PostgreSQL)" "docker-compose-sy.yml"
      ;;
    local)
      run_step "BT Django backend (local SQLite)" "$ROOT_DIR/backend" "$PYTHON_BIN" manage.py test myapp -v 2
      run_step "SY Django backend (local SQLite)" "$ROOT_DIR/sy_backend" "$PYTHON_BIN" manage.py test myapp -v 2
      ;;
    *)
      printf 'Unsupported FNTL_BACKEND_TEST_MODE=%s. Use "docker" or "local".\n' "$BACKEND_TEST_MODE" >&2
      exit 2
      ;;
  esac
}

run_backend_steps
run_step "Alarm desktop client unit tests" "$ROOT_DIR" "$PYTHON_BIN" -m unittest discover -s alarm_client/tests
run_step "BT serial agent unit tests" "$ROOT_DIR" "$PYTHON_BIN" -m unittest discover -s bt_agent_serial/tests
run_step "Frontend unit tests" "$ROOT_DIR/frontend" npm run test:unit
run_step "Frontend production build" "$ROOT_DIR/frontend" npm run build
run_step "Virtual backend unit tests" "$ROOT_DIR/virtual-backend" npm run test:unit
run_step "Virtual backend Playwright E2E" "$ROOT_DIR/virtual-backend" npm run test:e2e

printf '\nFNTL regression passed.\n'
