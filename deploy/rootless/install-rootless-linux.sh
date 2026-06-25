#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script is only for Linux Docker Engine hosts." >&2
  exit 1
fi

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this script as the non-root deployment user, not as root." >&2
  exit 1
fi

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    return 1
  fi
}

need_cmd docker
need_cmd dockerd-rootless-setuptool.sh
need_cmd newuidmap
need_cmd newgidmap

user_name="$(id -un)"
uid_value="$(id -u)"
rootless_socket="/run/user/${uid_value}/docker.sock"

if ! grep -q "^${user_name}:" /etc/subuid || ! grep -q "^${user_name}:" /etc/subgid; then
  cat >&2 <<EOF
Missing subordinate UID/GID ranges for ${user_name}.

Run as root, then rerun this script as ${user_name}:
  sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 ${user_name}
EOF
  exit 1
fi

if [[ "${BT_NMS_DISABLE_ROOTFUL_DOCKER:-0}" == "1" ]]; then
  sudo systemctl disable --now docker.service docker.socket || true
  sudo rm -f /var/run/docker.sock
fi

dockerd-rootless-setuptool.sh install
systemctl --user enable --now docker

if command -v loginctl >/dev/null 2>&1; then
  loginctl enable-linger "${user_name}" || cat >&2 <<EOF
Could not enable linger as ${user_name}. Run this as root if the service must
start without an interactive login:
  sudo loginctl enable-linger ${user_name}
EOF
fi

cat <<EOF
Rootless Docker setup command completed.

Use these environment variables for BT_NMS production commands:
  export DOCKER_HOST=unix://${rootless_socket}
  export DOCKER_HOST_SOCKET=${rootless_socket}
  export DATA_DIR=\$HOME/bt_nms_data

Then run:
  deploy/rootless/preflight-rootless-bt-nms.sh
EOF
