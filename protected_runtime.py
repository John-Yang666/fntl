from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


DATA_ROOT_ENV = "BT_NMS_DATA_ROOT"
PROTECTED_HOME_ENV = "BT_NMS_PROTECTED_HOME"
WINDOWS_DATA_DIR = "BT_NMS"


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def data_root() -> Path:
    custom_root = str(os.environ.get(DATA_ROOT_ENV, "")).strip()
    if custom_root:
        root = Path(custom_root).expanduser()
    elif os.name == "nt":
        root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / WINDOWS_DATA_DIR
    else:
        root = Path.home() / ".bt_nms"
    root.mkdir(parents=True, exist_ok=True)
    return root


def app_data_dir(app_name: str) -> Path:
    path = data_root() / app_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def agent_config_path(app_name: str) -> Path:
    return app_data_dir(app_name) / "config.json"


def runtime_config_path(app_name: str, filename: str = "runtime_config.json") -> Path:
    return app_data_dir(app_name) / filename


def sqlite_path(app_name: str, filename: str) -> Path:
    return app_data_dir(app_name) / filename


def lock_path(app_name: str, filename: str) -> Path:
    return app_data_dir(app_name) / filename


def child_process_popen_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {"start_new_session": True}

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {"creationflags": creationflags, "startupinfo": startupinfo}


def terminate_child_process(proc: Any, *, terminate_timeout: float = 2.5, kill_timeout: float = 2.5) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
    except Exception:
        pass

    try:
        proc.terminate()
    except Exception:
        pass

    try:
        proc.wait(timeout=terminate_timeout)
        return
    except Exception:
        pass

    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            proc.kill()
        except Exception:
            pass

    try:
        proc.wait(timeout=kill_timeout)
        return
    except Exception:
        pass

    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            proc.kill()
        except Exception:
            pass

    try:
        proc.wait(timeout=kill_timeout)
    except Exception:
        pass


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_json_file(path: Path, payload: Any) -> Path:
    if not path.exists():
        write_json_file(path, payload)
    return path


def protected_home(default_root: Path | None = None) -> Path:
    configured = str(os.environ.get(PROTECTED_HOME_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser()
    if default_root is not None:
        return default_root
    return repo_root()


def _iter_search_roots(extra_roots: Iterable[Path]) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in extra_roots:
        try:
            path = raw.resolve()
        except Exception:
            path = raw
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        roots.append(path)
    return roots


def resolve_protected_executable(app_name: str, *, extra_roots: Iterable[Path] = ()) -> Path | None:
    current_path = Path(sys.argv[0]).resolve()
    search_roots = _iter_search_roots(
        [
            protected_home(repo_root()),
            current_path.parent,
            current_path.parent.parent,
            current_path.parent.parent.parent,
            *extra_roots,
        ]
    )
    checked: set[str] = set()
    for root in search_roots:
        for candidate in (
            root / "apps" / app_name / f"{app_name}.exe",
            root / "apps" / f"{app_name}.dist" / f"{app_name}.exe",
            root / app_name / f"{app_name}.exe",
            root / f"{app_name}.dist" / f"{app_name}.exe",
            root / f"{app_name}.exe",
        ):
            key = str(candidate)
            if key in checked:
                continue
            checked.add(key)
            if candidate.exists():
                return candidate
    return None


def resolve_launch_command(app_name: str, script_path: Path) -> tuple[list[str], Path]:
    executable = resolve_protected_executable(app_name, extra_roots=[script_path.parent, script_path.parent.parent])
    if executable is not None:
        return [str(executable)], executable.parent
    if script_path.exists():
        return [sys.executable, str(script_path)], repo_root()
    raise FileNotFoundError(f"unable to locate {app_name}.exe or fallback script: {script_path}")
