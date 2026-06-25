# BT_NMS Linux Rootless Docker

This directory contains helper scripts for running the production compose stacks
against a Linux Docker Engine rootless daemon.

Rootless mode is a host-level deployment choice. Do not run these scripts on
Docker Desktop for macOS or Windows.

## Install

Run as the non-root deployment user:

```bash
deploy/rootless/install-rootless-linux.sh
```

If the host must disable the rootful Docker daemon during the cutover:

```bash
BT_NMS_DISABLE_ROOTFUL_DOCKER=1 deploy/rootless/install-rootless-linux.sh
```

## Environment

Set these variables before running production compose commands:

```bash
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
export DOCKER_HOST_SOCKET=/run/user/$(id -u)/docker.sock
export DATA_DIR=$HOME/bt_nms_data
```

`DOCKER_HOST` selects the rootless daemon. `DOCKER_HOST_SOCKET` is the host path
mounted by the optional Portainer service when the `docker-admin` profile is
enabled.

## Preflight

```bash
deploy/rootless/preflight-rootless-bt-nms.sh
```

The preflight checks the rootless socket, subordinate UID/GID ranges, compose
rendering, and the selected data directory.
