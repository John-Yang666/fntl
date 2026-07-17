from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    def __init__(self, system: str, message: str, status: int | None = None):
        super().__init__(message)
        self.system = system
        self.status = status


@dataclass
class HttpResponse:
    status: int
    data: bytes


Transport = Callable[[Request, bytes | None, float], HttpResponse]


def default_transport(request: Request, body: bytes | None, timeout: float) -> HttpResponse:
    with urlopen(request, data=body, timeout=timeout) as response:  # noqa: S310 - user-configured frontend API URL
        return HttpResponse(status=response.status, data=response.read())


class ApiClient:
    def __init__(
        self,
        system: str,
        api_base: str,
        *,
        transport: Transport = default_transport,
        timeout: float = 5.0,
    ):
        self.system = system
        self.api_base = api_base.rstrip("/") + "/"
        self.transport = transport
        self.timeout = timeout
        self.access_token: str | None = None
        self.refresh_token: str | None = None

    def login(self, username: str, password: str) -> None:
        payload = self._request_json("POST", "token/", {"username": username, "password": password}, auth=False)
        access = payload.get("access") if isinstance(payload, dict) else None
        refresh = payload.get("refresh") if isinstance(payload, dict) else None
        if not access or not refresh:
            raise ApiError(self.system, f"{self.system.upper()} login response missing tokens")
        self.access_token = str(access)
        self.refresh_token = str(refresh)

    def refresh_access_token(self) -> None:
        if not self.refresh_token:
            raise ApiError(self.system, f"{self.system.upper()} refresh token is missing", status=401)
        payload = self._request_json("POST", "token/refresh/", {"refresh": self.refresh_token}, auth=False)
        access = payload.get("access") if isinstance(payload, dict) else None
        if not access:
            raise ApiError(self.system, f"{self.system.upper()} refresh response missing access token", status=401)
        self.access_token = str(access)
        refresh = payload.get("refresh") if isinstance(payload, dict) else None
        if refresh:
            self.refresh_token = str(refresh)

    def get_json(self, endpoint_or_url: str) -> Any:
        return self.request_json("GET", endpoint_or_url)

    def request_json(self, method: str, endpoint_or_url: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            return self._request_json(method, endpoint_or_url, payload, auth=True)
        except ApiError as exc:
            if exc.status != 401:
                raise
            self.refresh_access_token()
            return self._request_json(method, endpoint_or_url, payload, auth=True)

    def websocket_url(self) -> str:
        parsed = urlsplit(self.api_base.rstrip("/"))
        scheme = "wss" if parsed.scheme == "https" else "ws"
        api_suffix = f"/{self.system}-api"
        path = parsed.path.rstrip("/")
        if path.endswith(api_suffix):
            path = f"{path[:-len(api_suffix)]}/{self.system}-ws/alarms/"
        elif path.endswith("/api"):
            path = f"{path[:-4]}/ws/alarms/"
        else:
            path = f"/{self.system}-ws/alarms/"
        return urlunsplit((scheme, parsed.netloc, path, "", ""))

    def list_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        next_url: str | None = "devices/"
        while next_url:
            payload = self.get_json(next_url)
            if isinstance(payload, dict) and isinstance(payload.get("results"), list):
                devices.extend(item for item in payload["results"] if isinstance(item, dict))
                next_value = payload.get("next")
                next_url = str(next_value) if next_value else None
            elif isinstance(payload, list):
                devices.extend(item for item in payload if isinstance(item, dict))
                next_url = None
            else:
                raise ApiError(self.system, f"{self.system.upper()} devices response has unexpected shape")
        return devices

    def list_active_alarms(self) -> list[dict[str, Any]]:
        payload = self.get_json("active-alarms/")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            return [item for item in payload["results"] if isinstance(item, dict)]
        raise ApiError(self.system, f"{self.system.upper()} active alarms response has unexpected shape")

    def get_monitoring_preference(self) -> set[str]:
        payload = self.get_json("monitoring-preference/")
        if not isinstance(payload, dict) or not isinstance(payload.get("device_ids"), list):
            raise ApiError(self.system, f"{self.system.upper()} monitoring preference has unexpected shape")
        return {f"{self.system}:{int(device_id)}" for device_id in payload["device_ids"]}

    def save_monitoring_preference(self, selected_device_ids: set[int], available_device_ids: set[int]) -> None:
        selection_mode = "all" if selected_device_ids == available_device_ids else "custom"
        self.request_json("PUT", "monitoring-preference/", {
            "selection_mode": selection_mode,
            "device_ids": sorted(selected_device_ids),
        })

    def list_alarm_details(self) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for alarm in self.list_active_alarms():
            details.append({**alarm, "system": self.system, "source": "current", "timestamp_end": None})

        next_url: str | None = "alerts/?is_confirmed=false&monitored=true&page_size=500"
        while next_url:
            payload = self.get_json(next_url)
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ApiError(self.system, f"{self.system.upper()} alarm history response has unexpected shape")
            for alarm in payload["results"]:
                if isinstance(alarm, dict):
                    details.append({
                        **alarm,
                        "system": self.system,
                        "source": "history",
                        "confirmed": bool(alarm.get("is_confirmed")),
                    })
            next_value = payload.get("next")
            next_url = str(next_value) if next_value else None
        return details

    def _request_json(self, method: str, endpoint_or_url: str, payload: dict[str, Any] | None, *, auth: bool) -> Any:
        headers = {"Accept": "application/json"}
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth:
            if not self.access_token:
                raise ApiError(self.system, f"{self.system.upper()} access token is missing", status=401)
            headers["Authorization"] = f"Bearer {self.access_token}"

        url = self._build_url(endpoint_or_url)
        request = Request(url, data=body, headers=headers, method=method)
        try:
            response = self.transport(request, body, self.timeout)
        except HTTPError as exc:
            raise ApiError(self.system, f"{self.system.upper()} API HTTP {exc.code}", status=exc.code) from exc
        except URLError as exc:
            raise ApiError(self.system, f"{self.system.upper()} API network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ApiError(self.system, f"{self.system.upper()} API request timed out") from exc

        if response.status < 200 or response.status >= 300:
            raise ApiError(self.system, f"{self.system.upper()} API HTTP {response.status}", status=response.status)
        if not response.data:
            return None
        try:
            return json.loads(response.data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(self.system, f"{self.system.upper()} API returned invalid JSON") from exc

    def _build_url(self, endpoint_or_url: str) -> str:
        if endpoint_or_url.startswith("http://") or endpoint_or_url.startswith("https://"):
            return endpoint_or_url
        return urljoin(self.api_base, endpoint_or_url.lstrip("/"))
