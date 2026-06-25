#!/usr/bin/env bash
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}" || exit 1

failures=0

ok() {
  printf '[OK] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1" >&2
}

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  failures=$((failures + 1))
}

need_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    ok "found command: $1"
  else
    fail "missing command: $1"
  fi
}

if [[ "$(uname -s)" == "Linux" ]]; then
  ok "host OS is Linux"
else
  fail "rootless production deployment is intended for Linux Docker Engine hosts, not Docker Desktop on macOS/Windows"
fi

if [[ "$(id -u)" -eq 0 ]]; then
  fail "run as the non-root rootless Docker user"
else
  ok "running as non-root user $(id -un) ($(id -u))"
fi

need_cmd docker
if docker compose version >/dev/null 2>&1; then
  ok "docker compose is available"
else
  fail "docker compose plugin is not available"
fi
need_cmd newuidmap
need_cmd newgidmap

user_name="$(id -un)"
uid_value="$(id -u)"
expected_socket="/run/user/${uid_value}/docker.sock"

check_subid() {
  local file="$1"
  local label="$2"
  local line
  line="$(grep "^${user_name}:" "${file}" | head -n 1 || true)"
  if [[ -z "${line}" ]]; then
    fail "missing ${label} range for ${user_name} in ${file}"
    return
  fi

  local count
  count="$(printf '%s' "${line}" | awk -F: '{print $3}')"
  if [[ "${count}" =~ ^[0-9]+$ ]] && [[ "${count}" -ge 65536 ]]; then
    ok "${label} range is present: ${line}"
  else
    fail "${label} range must contain at least 65536 IDs: ${line}"
  fi
}

check_subid /etc/subuid subuid
check_subid /etc/subgid subgid

if [[ -S "${expected_socket}" ]]; then
  ok "rootless Docker socket exists: ${expected_socket}"
else
  fail "rootless Docker socket not found: ${expected_socket}"
fi

if [[ "${DOCKER_HOST:-}" == "unix://${expected_socket}" ]]; then
  ok "DOCKER_HOST points to the rootless socket"
else
  warn "set DOCKER_HOST=unix://${expected_socket} before running production compose commands"
fi

if [[ "${DOCKER_HOST_SOCKET:-}" == "${expected_socket}" ]]; then
  ok "DOCKER_HOST_SOCKET points to the rootless socket"
else
  warn "set DOCKER_HOST_SOCKET=${expected_socket} so Portainer mounts the rootless socket when enabled"
fi

security_options="$(docker info --format '{{range .SecurityOptions}}{{println .}}{{end}}' 2>/dev/null || true)"
if printf '%s\n' "${security_options}" | grep -qi rootless; then
  ok "docker info reports rootless security option"
else
  fail "docker info does not report rootless mode"
fi

data_dir="${DATA_DIR:-}"
if [[ -z "${data_dir}" ]]; then
  fail "set DATA_DIR to a rootless-user-owned path such as ${HOME}/bt_nms_data"
elif [[ "${data_dir}" == /srv/* ]]; then
  warn "DATA_DIR is under /srv; confirm it is owned and writable by $(id -un): ${data_dir}"
elif [[ -d "${data_dir}" && -w "${data_dir}" ]]; then
  ok "DATA_DIR is writable: ${data_dir}"
else
  parent_dir="$(dirname "${data_dir}")"
  if [[ -w "${parent_dir}" ]]; then
    ok "DATA_DIR can be created by current user: ${data_dir}"
  else
    fail "DATA_DIR parent is not writable by current user: ${parent_dir}"
  fi
fi

export DOCKER_HOST_SOCKET="${DOCKER_HOST_SOCKET:-${expected_socket}}"
export DATA_DIR="${DATA_DIR:-${HOME}/bt_nms_data}"

if docker compose -f docker-compose-prod.yml --profile docker-admin config >/tmp/bt-nms-rootless-bt-compose.yml 2>/tmp/bt-nms-rootless-bt-compose.err; then
  ok "BT production compose renders with rootless socket settings"
else
  fail "BT production compose config failed; see /tmp/bt-nms-rootless-bt-compose.err"
fi

if docker compose -f docker-compose-sy-prod.yml --profile docker-admin config >/tmp/bt-nms-rootless-sy-compose.yml 2>/tmp/bt-nms-rootless-sy-compose.err; then
  ok "SY production compose renders with rootless socket settings"
else
  fail "SY production compose config failed; see /tmp/bt-nms-rootless-sy-compose.err"
fi

if [[ "${failures}" -eq 0 ]]; then
  ok "rootless preflight passed"
  exit 0
fi

printf '[FAIL] rootless preflight found %s blocking issue(s)\n' "${failures}" >&2
exit 1
