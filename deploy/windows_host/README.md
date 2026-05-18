# Windows Host Deployment

## Protected Deploy

Build the protected Windows bundle on an internal build machine:

```powershell
cd deploy/windows_host
.\build_protected_agents.ps1
```

Bundle output:

```text
deploy/windows_host/artifacts/windows_agents/
  apps/
  scripts/
  templates/
```

Copy only that bundle to the Windows deployment machine. Start from:

```text
scripts\run_bt_agent_ui.bat
scripts\run_sy_agent_ui.bat
scripts\run_sy_agent_sub_ui.bat
scripts\run_agents.bat
```

Protected deploy uses compiled `exe` programs only. The target machine does not need Python.

Editable runtime data lives under:

```text
%ProgramData%\BT_NMS\bt_agent\
  config.json
  runtime_config.json
  bt_agent_ui.sqlite3

%ProgramData%\BT_NMS\sy_agent\
  config.json
  runtime_config.json
  runtime_sub_agent_config.json
  sy_agent_ui.sqlite3
  sy_agent_sub_ui.sqlite3
```

Notes:

- `bt_agent.exe` and `sy_agent.exe` read external `config.json` by default
- UI programs also persist their local state to sqlite under `%ProgramData%\BT_NMS`
- When a UI starts a child agent, it writes `runtime_config.json` and passes it through `BT_AGENT_CONFIG_JSON` or `SY_AGENT_CONFIG_JSON`
- Existing restart/backoff behavior stays in the bat wrappers

## Maintenance / Dev

The source-based scripts in this folder are now maintenance-only workflows for internal use:

- `prepare_frontend_offline_editing.bat`
- `build_and_apply_frontend_dist_offline.bat`
- `build_and_export_frontend_prod_image.bat`
- `import_and_update_frontend_prod_image.bat`

Use these only on trusted maintenance machines where keeping source code is acceptable.

## Runtime Config

- `bt_agent` blocks IPs through `filters.blocked_ips` in `%ProgramData%\BT_NMS\bt_agent\config.json`
- `bt_agent_serial` reads one TestData serial device and stores settings in `%ProgramData%\BT_NMS\bt_agent_serial\config.json`
- `sy_agent` terminal UI settings remain under the `ui` section of `%ProgramData%\BT_NMS\sy_agent\config.json`

Legacy `.py` config import/export remains available inside the UI as a development-only compatibility path. Protected deployment should use JSON only.
