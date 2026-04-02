# Windows host deployment for bt_agent and sy_agent

This layout is for running `bt_agent` and `sy_agent` directly on a Windows host with the host Python installation.

## Expected layout on the Windows host

Clone or copy this repo to a stable path:

```text
D:\BT_NMS\
  bt_agent\
  sy_agent\
  deploy\windows_host\
```

## First-time setup

From `cmd.exe`:

```bat
cd /d D:\BT_NMS\deploy\windows_host
```

Then edit:

- `bt_agent\config.py`
- `sy_agent\config.py`

## Start commands

Start each agent in its own console:

```bat
cd /d D:\BT_NMS\deploy\windows_host
run_bt_agent.bat
run_sy_agent.bat
```

Start both:

```bat
cd /d D:\BT_NMS\deploy\windows_host
start_agents_on_boot.bat
```

For Windows boot or Startup-folder use:

```bat
cd /d D:\BT_NMS\deploy\windows_host
start_agents_on_boot.bat
```

## Frontend offline update helpers

Build and export the production frontend image on a Windows machine with internet:

```bat
cd /d D:\BT_NMS\deploy\windows_host
build_and_export_frontend_prod_image.bat
```

This writes:

```text
D:\BT_NMS\deploy\windows_host\artifacts\my_vue_prod.tar
```

On the offline Windows deployment machine, import that tar and recreate the frontend container:

```bat
cd /d D:\BT_NMS\deploy\windows_host
import_and_update_frontend_prod_image.bat
```

You may also pass a custom tar path:

```bat
import_and_update_frontend_prod_image.bat E:\packages\my_vue_prod.tar
```

## Small offline frontend edits on the production machine

If the production machine itself needs small frontend source changes and must apply them offline, use host-built `dist` instead of rebuilding `my_vue:prod`.

One-time online preparation:

```bat
cd /d D:\BT_NMS\deploy\windows_host
prepare_frontend_offline_editing.bat
```

After that, each offline update is:

1. Edit files under `D:\BT_NMS\frontend\src`
2. Rebuild and apply:

```bat
cd /d D:\BT_NMS\deploy\windows_host
build_and_apply_frontend_dist_offline.bat
```

This command rebuilds `frontend\dist` offline using local npm cache and recreates the `vue` service with:

```text
docker-compose-prod.yml
docker-compose-prod.frontend-local.yml
```

So the production frontend serves `D:\BT_NMS\frontend\dist` from the host.

## Notes

- Both agents read runtime configuration from their own Python config files:
  - `bt_agent\config.py`
  - `sy_agent\config.py`
- `sy_agent` terminal UI is configured in `sy_agent\config.py` under `ui`:
  - `mode = "dashboard"`: default top-style single-screen refresh view
  - `mode = "plain"`: compact rolling text logs for troubleshooting or log capture
  - `refresh_sec`: dashboard refresh interval in seconds
  - `event_buffer_size`: recent event count shown at the bottom of the dashboard
  - `ansi = "auto" | "always" | "never"`: set to `never` if Windows `cmd` ANSI refresh looks wrong
- `sy_agent` background health probe is configured in `sy_agent\config.py` under `probe`:
  - `enable`: probe the non-preferred side in the background
  - `interval_sec`: probe interval; keep this low-frequency
  - `timeout_sec`: probe timeout for the backup side A2 read
  - `queue_threshold`: skip probing if receive queues are already busy
  - `cooldown_after_fault_sec`: skip probing for a short time after recent `NoResp` or `Unmatch`
- The scripts use the host Python from `py -3` first, then fall back to `python`.
- `bt_agent` blocked IPs are configured through `filters.blocked_ips` in `bt_agent\config.py`.
- Default ports in code are different:
  - `bt_agent`: Redis `36379`, UDP listen `38315`
  - `sy_agent`: Redis `36380`
- `start_agents_on_boot.bat` now opens two visible `cmd` windows and keeps them open with live agent output.
