# Protected Deployment

## Build Machine

Windows agent bundle:

```powershell
cd deploy/windows_host
.\build_protected_agents.ps1
```

Output bundle:

```text
deploy/windows_host/artifacts/windows_agents/
  apps/
  scripts/
  templates/
```

Linux/Docker protected images:

```bash
cd deploy/protected
./export_protected_images.sh
```

This writes:

```text
deploy/protected/artifacts/protected-images.tar
```

## Deployment Machine

For Windows agents, copy only the built `windows_agents` bundle. Start from:

```text
scripts/run_bt_agent_ui.bat
scripts/run_sy_agent_ui.bat
scripts/run_sy_agent_sub_ui.bat
scripts/run_agents.bat
```

Runtime state and editable configuration are stored under:

```text
%ProgramData%\BT_NMS\bt_agent\
%ProgramData%\BT_NMS\sy_agent\
```

For Docker deployment, copy only the image tar and compose files, then:

```bash
cd deploy/protected
./import_and_start_protected.sh /path/to/protected-images.tar all
```

## Modes

- `protected deploy`: deploy only bundle artifacts or Docker image tar files; no source tree on the target machine
- `maintenance/dev`: source-based workflows such as `prepare_frontend_offline_editing.bat`; keep these only on internal maintenance machines
