import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib import error, parse, request

from .frames import build_analog_packet, build_switch_packet
from .streams import find_stream_entry, latest_stream_id, xadd_packet

ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_DEVICE_IDS = [9101, 9102]
TEST_IPS = {9101: "192.168.91.101", 9102: "192.168.91.102"}
TEST_DEPOT = "Docker测试车间-BT"
TEST_LINE = "Docker测试线路-BT"


class HttpClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        transport: str = "host",
        compose_file: str = "docker-compose.yml",
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
depot, _ = Depot.objects.get_or_create(name={TEST_DEPOT!r}, defaults={{"ordering": 9010}})
line, _ = Line.objects.get_or_create(name={TEST_LINE!r}, defaults={{"ordering": 9010}})
devices = [
    (9101, "BT-Docker-Test-01", "192.168.91.101", 0, 2),
    (9102, "BT-Docker-Test-02", "192.168.91.102", 1, 1),
]
for device_id, name, ip, x, neighbor_dir in devices:
    Device.objects.update_or_create(
        device_id=device_id,
        defaults={{
            "name": name,
            "depot": depot,
            "line": line,
            "ip_address": ip,
            "x_coordinate": 100 + x * 180,
            "y_coordinate": 120,
            "direction1_neighbor_id": 9102 if device_id == 9101 else 9101,
            "direction1_neighbor_direction": neighbor_dir,
            "direction2_neighbor_id": 0,
            "direction2_neighbor_direction": 1,
            "direction1_enabled": True,
            "direction2_enabled": True,
            "alarm_filters": [],
            "remark": "bt_test_agent",
        }},
    )
print("bt test data ready")
"""
    _run_shell(compose_file, code)


def cleanup_data(compose_file: str) -> None:
    ids = TEST_DEVICE_IDS
    code = f"""
from django.apps import apps
ids = {ids!r}
for model_name in ["SwitchData", "AnalogData", "AlarmActive", "AlarmData", "RelayAction", "UserOperation"]:
    try:
        model = apps.get_model("myapp", model_name)
    except LookupError:
        continue
    if any(field.name == "device" for field in model._meta.fields):
        model.objects.filter(device_id__in=ids).delete()
apps.get_model("myapp", "Device").objects.filter(device_id__in=ids).delete()
apps.get_model("myapp", "Line").objects.filter(name={TEST_LINE!r}).delete()
apps.get_model("myapp", "Depot").objects.filter(name={TEST_DEPOT!r}).delete()
print("bt test data cleaned")
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


def _connect_redis(host: str, port: int):
    import redis

    client = redis.Redis(host=host, port=port, db=0, decode_responses=False)
    client.ping()
    return client


def _cleanup_after_run(args: argparse.Namespace, redis_client, packet_ids: List[bytes], command_ids: List[bytes], failed: bool) -> None:
    keep_artifacts = args.keep_on_fail and failed
    if keep_artifacts:
        print("BT test failed; keeping test data because --keep-on-fail was set.", file=sys.stderr)
        return

    errors = []
    try:
        cleanup_data(args.compose_file)
    except Exception as exc:
        errors.append(f"database cleanup failed: {exc}")

    if packet_ids:
        try:
            redis_client.xdel(args.packet_stream, *packet_ids)
        except Exception as exc:
            errors.append(f"{args.packet_stream} cleanup failed: {exc}")

    if command_ids:
        try:
            redis_client.xdel(args.cmd_stream, *command_ids)
        except Exception as exc:
            errors.append(f"{args.cmd_stream} cleanup failed: {exc}")

    if errors:
        message = "; ".join(errors)
        if failed:
            print(f"BT cleanup warning after failure: {message}", file=sys.stderr)
        else:
            raise RuntimeError(f"BT cleanup failed: {message}")


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
    created_stream_ids: List[bytes] = []
    command_stream_ids: List[bytes] = []
    cmd_start_id = latest_stream_id(redis_client, args.cmd_stream)
    failed = True
    try:
        prepare_data(args.compose_file)
        if args.receiver_cache_wait > 0:
            print(f"WAIT BT receiver cache refresh {args.receiver_cache_wait:.1f}s")
            time.sleep(args.receiver_cache_wait)

        zero = bytes(46)
        changed = bytearray(46)
        changed[3] = 0x01
        created_stream_ids.append(
            xadd_packet(redis_client, stream_name=args.packet_stream, device_id=9101, ip_address=TEST_IPS[9101], packet=build_switch_packet(zero))
        )
        created_stream_ids.append(
            xadd_packet(redis_client, stream_name=args.packet_stream, device_id=9101, ip_address=TEST_IPS[9101], packet=build_switch_packet(bytes(changed)))
        )
        created_stream_ids.append(
            xadd_packet(
                redis_client,
                stream_name=args.packet_stream,
                device_id=9101,
                ip_address=TEST_IPS[9101],
                packet=build_analog_packet(voltage_1=1210, current_1=120, voltage_2=1200, current_2=110),
            )
        )

        wait_until("BT switch-data", args.timeout, lambda: _count(http.get_json("/api/switch-data/", {"device": 9101, "page_size": 10})) >= 1)
        wait_until("BT analog-data", args.timeout, lambda: _count(http.get_json("/api/analog-data/", {"device": 9101, "page_size": 10})) >= 1)
        wait_until("BT relay-actions", args.timeout, lambda: _count(http.get_json("/api/relay-actions/", {"device": 9101, "page_size": 10})) >= 1)
        wait_until(
            "BT active-alarms",
            args.timeout,
            lambda: any(item.get("device_id") == 9101 for item in http.get_json("/api/active-alarms/")),
        )

        http.post_json("/api/send-command/9101/", {"function_code": 1, "operation": 2, "time": int(time.time())})
        entry_id, fields = find_stream_entry(
            redis_client,
            stream_name=args.cmd_stream,
            start_id=cmd_start_id,
            predicate=lambda item: item.get(b"ip") == TEST_IPS[9101].encode(),
            timeout_sec=args.timeout,
        )
        command_stream_ids.append(entry_id)
        print(f"PASS BT command stream id={entry_id!r} payload={fields.get(b'payload', b'').hex()}")
        wait_until("BT user-operations", args.timeout, lambda: _count(http.get_json("/api/user-operations/", {"device": 9101, "page_size": 10})) >= 1)
        print("BT docker test agent passed.")
        failed = False
        return 0
    except Exception:
        raise
    finally:
        _cleanup_after_run(args, redis_client, created_stream_ids, command_stream_ids, failed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BT Docker test agent")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=36379)
    parser.add_argument("--packet-stream", default="stream:udp:packets")
    parser.add_argument("--cmd-stream", default="stream:udp:cmd")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--http-transport", choices=["host", "compose"], default="host")
    parser.add_argument("--compose-service", default="web")
    parser.add_argument("--receiver-cache-wait", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument("--keep-on-fail", action="store_true")
    return parser


def main(argv: List[str] = None) -> int:
    return run(build_parser().parse_args(argv))
