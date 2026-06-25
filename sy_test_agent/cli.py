import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib import error, parse, request

from .frames import build_a1_response, build_a2_response
from .streams import find_stream_entry, latest_stream_id, parse_command_payload, xadd_raw

ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_DEVICE_IDS = [9201, 9202]
TEST_DEPOT = "Docker测试车间-SY"
TEST_LINE = "Docker测试线路-SY"


class HttpClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        transport: str = "host",
        compose_file: str = "docker-compose-sy.yml",
        compose_service: str = "web",
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.access_token = ""
        self.transport = transport
        self.compose_file = compose_file
        self.compose_service = compose_service

    def login(self) -> None:
        payload = self.post_json("/api/token/", {"username": self.username, "password": self.password}, auth=False)
        self.access_token = str(payload["access"])

    def get_json(self, path: str, params: Dict[str, Any] = None) -> Any:
        query = f"?{parse.urlencode(params or {})}" if params else ""
        return self._json("GET", path + query)

    def post_json(self, path: str, payload: Dict[str, Any], auth: bool = True) -> Any:
        return self._json("POST", path, payload=payload, auth=auth)

    def _json(self, method: str, path: str, payload: Dict[str, Any] = None, auth: bool = True) -> Any:
        if self.transport == "compose":
            return self._compose_json(method, path, payload=payload, auth=auth)

        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(self.base_url + path, data=data, method=method)
        req.add_header("content-type", "application/json")
        if auth and self.access_token:
            req.add_header("authorization", f"Bearer {self.access_token}")
        try:
            with request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc

    def _compose_json(self, method: str, path: str, payload: Dict[str, Any] = None, auth: bool = True) -> Any:
        headers = {"content-type": "application/json"}
        if auth and self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        spec = {
            "method": method,
            "url": self.base_url + path,
            "payload": payload,
            "headers": headers,
        }
        code = r"""
import json
import sys
from urllib import error, request

spec = json.load(sys.stdin)
data = None if spec["payload"] is None else json.dumps(spec["payload"]).encode("utf-8")
req = request.Request(spec["url"], data=data, method=spec["method"])
for key, value in spec["headers"].items():
    req.add_header(key, value)
try:
    with request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        print(raw if raw else "{}")
except error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
    sys.exit(1)
"""
        result = subprocess.run(
            ["docker", "compose", "-f", self.compose_file, "exec", "-T", self.compose_service, "python", "-c", code],
            cwd=str(ROOT_DIR),
            text=True,
            input=json.dumps(spec),
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{method} {path} failed in compose service {self.compose_service}: {result.stderr.strip()}")
        raw = result.stdout.strip()
        return json.loads(raw) if raw else {}


def _run_shell(compose_file: str, code: str) -> None:
    cmd = ["docker", "compose", "-f", compose_file, "exec", "-T", "web", "python", "manage.py", "shell", "-c", code]
    result = subprocess.run(cmd, cwd=str(ROOT_DIR), text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker compose shell failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def prepare_data(compose_file: str) -> None:
    code = f"""
from myapp.models import Depot, Line, Device
depot, _ = Depot.objects.get_or_create(name={TEST_DEPOT!r}, defaults={{"ordering": 9020}})
line, _ = Line.objects.get_or_create(name={TEST_LINE!r}, defaults={{"ordering": 9020}})
devices = [
    (9201, "SY-Docker-Test-01", "192.168.92.101", 0),
    (9202, "SY-Docker-Test-02", "192.168.92.102", 1),
]
for device_id, name, ip, x in devices:
    Device.objects.update_or_create(
        device_id=device_id,
        defaults={{
            "name": name,
            "depot": depot,
            "line": line,
            "ip_address": ip,
            "x_coordinate": 100 + x * 180,
            "y_coordinate": 220,
            "direction1_neighbor_id": 9202 if device_id == 9201 else 9201,
            "direction1_neighbor_direction": 2,
            "direction2_neighbor_id": 0,
            "direction2_neighbor_direction": 1,
            "direction3_enabled": False,
            "direction1_enabled": True,
            "direction2_enabled": True,
            "alarm_filters": [],
            "remark": "sy_test_agent",
        }},
    )
print("sy test data ready")
"""
    _run_shell(compose_file, code)


def cleanup_data(compose_file: str) -> None:
    ids = TEST_DEVICE_IDS
    code = f"""
from django.apps import apps
ids = {ids!r}
for model_name in ["SwitchData", "ChangeBitEvent", "RawFrameLog", "AlarmActive", "AlarmData", "RelayAction", "UserOperation"]:
    try:
        model = apps.get_model("myapp", model_name)
    except LookupError:
        continue
    if any(field.name == "device" for field in model._meta.fields):
        model.objects.filter(device_id__in=ids).delete()
apps.get_model("myapp", "Device").objects.filter(device_id__in=ids).delete()
apps.get_model("myapp", "Line").objects.filter(name={TEST_LINE!r}).delete()
apps.get_model("myapp", "Depot").objects.filter(name={TEST_DEPOT!r}).delete()
print("sy test data cleaned")
"""
    _run_shell(compose_file, code)


def wait_until(label: str, timeout_sec: float, probe: Callable[[], bool]) -> None:
    deadline = time.monotonic() + timeout_sec
    last_error = None
    while time.monotonic() < deadline:
        try:
            if probe():
                print(f"PASS {label}")
                return
        except Exception as exc:
            last_error = exc
        time.sleep(0.5)
    detail = f": {last_error}" if last_error else ""
    raise TimeoutError(f"timeout waiting for {label}{detail}")


def _count(payload: Any) -> int:
    if isinstance(payload, dict) and "count" in payload:
        return int(payload["count"] or 0)
    if isinstance(payload, list):
        return len(payload)
    return 0


def _has_device_switch_data(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("latest_switch"):
        return True
    switch_hex = payload.get("hex")
    return isinstance(switch_hex, str) and bool(switch_hex.strip())


def _connect_redis(host: str, port: int):
    import redis

    client = redis.Redis(host=host, port=port, db=0, decode_responses=True)
    client.ping()
    return client


def _cleanup_after_run(args: argparse.Namespace, redis_client, raw_ids: List[str], command_ids: List[str], failed: bool) -> None:
    keep_artifacts = args.keep_on_fail and failed
    if keep_artifacts:
        print("SY test failed; keeping test data because --keep-on-fail was set.", file=sys.stderr)
        return

    errors = []
    try:
        cleanup_data(args.compose_file)
    except Exception as exc:
        errors.append(f"database cleanup failed: {exc}")

    if raw_ids:
        try:
            redis_client.xdel(args.raw_stream, *raw_ids)
        except Exception as exc:
            errors.append(f"{args.raw_stream} cleanup failed: {exc}")

    if command_ids:
        try:
            redis_client.xdel(args.cmd_stream, *command_ids)
        except Exception as exc:
            errors.append(f"{args.cmd_stream} cleanup failed: {exc}")

    if errors:
        message = "; ".join(errors)
        if failed:
            print(f"SY cleanup warning after failure: {message}", file=sys.stderr)
        else:
            raise RuntimeError(f"SY cleanup failed: {message}")


def run(args: argparse.Namespace) -> int:
    redis_client = _connect_redis(args.redis_host, args.redis_port)
    http = HttpClient(
        args.base_url,
        args.username,
        args.password,
        transport=args.http_transport,
        compose_file=args.compose_file,
        compose_service=args.compose_service,
    )
    http.login()
    created_stream_ids: List[str] = []
    command_stream_ids: List[str] = []
    cmd_start_id = latest_stream_id(redis_client, args.cmd_stream)
    failed = True
    try:
        prepare_data(args.compose_file)
        if args.receiver_cache_wait > 0:
            print(f"WAIT SY receiver cache refresh {args.receiver_cache_wait:.1f}s")
            time.sleep(args.receiver_cache_wait)

        status = bytearray(b"\x00\x00\x00\x00")
        created_stream_ids.append(
            xadd_raw(
                redis_client,
                stream_name=args.raw_stream,
                nms_id=9201,
                serial_id=241,
                line_id=1,
                req_cmd="A1",
                frame=build_a1_response(serial_id=241, status=bytes(status)),
            )
        )
        status[1] = 0x10
        created_stream_ids.append(
            xadd_raw(
                redis_client,
                stream_name=args.raw_stream,
                nms_id=9201,
                serial_id=241,
                line_id=1,
                req_cmd="A2",
                frame=build_a2_response(serial_id=241, status=bytes(status), bit_index=12, new_value=1),
            )
        )

        wait_until("SY switch-data", args.timeout, lambda: _count(http.get_json("/api/switch-data/", {"device": 9201, "page_size": 10})) >= 1)
        wait_until("SY relay-actions", args.timeout, lambda: _count(http.get_json("/api/relay-actions/", {"device": 9201, "page_size": 10})) >= 1)
        wait_until("SY device_switch_data", args.timeout, lambda: _has_device_switch_data(http.get_json("/api/device_switch_data/9201/")))
        wait_until("SY device-detail", args.timeout, lambda: http.get_json("/api/device-detail/9201/").get("device_id") == 9201)
        wait_until(
            "SY active-alarms endpoint",
            args.timeout,
            lambda: isinstance(http.get_json("/api/active-alarms/"), list),
        )

        http.post_json("/api/sy/send-command/9201/", {"cmd_type": "BB", "bb_name": "UP_FORCE_CABLE"})
        entry_id, fields = find_stream_entry(
            redis_client,
            stream_name=args.cmd_stream,
            start_id=cmd_start_id,
            predicate=lambda item: parse_command_payload(item).device_id == 9201,
            timeout_sec=args.timeout,
        )
        command_stream_ids.append(entry_id)
        command = parse_command_payload(fields)
        print(f"PASS SY command stream id={entry_id!r} command={command.command} frame={command.frame.hex()}")
        wait_until("SY user-operations", args.timeout, lambda: _count(http.get_json("/api/user-operations/", {"device": 9201, "page_size": 10})) >= 1)
        print("SY docker test agent passed.")
        failed = False
        return 0
    except Exception:
        raise
    finally:
        _cleanup_after_run(args, redis_client, created_stream_ids, command_stream_ids, failed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SY Docker test agent")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=36380)
    parser.add_argument("--raw-stream", default="sy.raw")
    parser.add_argument("--cmd-stream", default="sy-serial-commands")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--http-transport", choices=["host", "compose"], default="host")
    parser.add_argument("--compose-service", default="web")
    parser.add_argument("--receiver-cache-wait", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--compose-file", default="docker-compose-sy.yml")
    parser.add_argument("--keep-on-fail", action="store_true")
    return parser


def main(argv: List[str] = None) -> int:
    return run(build_parser().parse_args(argv))
