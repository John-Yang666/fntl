from pathlib import Path
from urllib.parse import urlsplit


def read_deploy_host_list(deploy_host_file: Path) -> list[str]:
    if not deploy_host_file.exists():
        return []

    values: list[str] = []
    for raw_line in deploy_host_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        values.extend(
            item.strip()
            for item in line.replace(";", ",").split(",")
            if item.strip()
        )
    return values


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _parsed_host(value: str) -> str:
    item = value.strip().rstrip("/")
    if not item:
        return ""
    parsed = urlsplit(item if "://" in item else f"//{item}")
    return (parsed.hostname or item.split(":", 1)[0]).strip()


def _origin_from_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _origin_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def build_allowed_hosts(base_hosts: list[str], deploy_hosts: list[str]) -> list[str]:
    allowed_hosts = list(dict.fromkeys(base_hosts))
    for value in deploy_hosts:
        _append_unique(allowed_hosts, _parsed_host(value))
    return allowed_hosts


def build_cors_allowed_origins(
    base_origins: list[str],
    deploy_hosts: list[str],
    *,
    http_ports: tuple[int, ...],
    https_ports: tuple[int, ...],
) -> list[str]:
    origins = list(dict.fromkeys(base_origins))
    for value in deploy_hosts:
        _append_unique(origins, _origin_from_url(value))
        host = _parsed_host(value)
        if not host:
            continue
        origin_host = _origin_host(host)
        for port in http_ports:
            _append_unique(origins, f"http://{origin_host}:{port}")
        for port in https_ports:
            _append_unique(origins, f"https://{origin_host}:{port}")
    return origins


def build_trusted_origins(
    base_origins: list[str],
    deploy_hosts: list[str],
    *,
    ports: tuple[int, ...],
) -> list[str]:
    return sorted(
        build_cors_allowed_origins(
            base_origins,
            deploy_hosts,
            http_ports=ports,
            https_ports=ports,
        )
    )
