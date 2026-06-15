#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

run_step "BT Django backend" "$ROOT_DIR/backend" "$PYTHON_BIN" manage.py test myapp -v 2
run_step "SY Django backend" "$ROOT_DIR/sy_backend" "$PYTHON_BIN" manage.py test myapp -v 2
run_step "Alarm desktop client unit tests" "$ROOT_DIR" "$PYTHON_BIN" -m unittest discover -s alarm_client/tests
run_step "BT serial agent unit tests" "$ROOT_DIR" "$PYTHON_BIN" -m unittest discover -s bt_agent_serial/tests
run_step "Frontend unit tests" "$ROOT_DIR/frontend" npm run test:unit
run_step "Frontend production build" "$ROOT_DIR/frontend" npm run build
run_step "Virtual backend unit tests" "$ROOT_DIR/virtual-backend" npm run test:unit
run_step "Virtual backend Playwright E2E" "$ROOT_DIR/virtual-backend" npm run test:e2e

printf '\nFNTL regression passed.\n'
