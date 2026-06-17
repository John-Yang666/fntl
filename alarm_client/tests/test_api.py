import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from alarm_client.api import ApiClient, HttpResponse


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.responses = []

    def queue_json(self, status, payload):
        self.responses.append(HttpResponse(status=status, data=json.dumps(payload).encode("utf-8")))

    def queue_error(self, status):
        self.responses.append(HTTPError("http://example.test", status, "error", hdrs=None, fp=None))

    def __call__(self, request: Request, body: bytes | None, timeout: float) -> HttpResponse:
        self.calls.append((request, body, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ApiClientTests(unittest.TestCase):
    def test_login_stores_access_and_refresh_tokens(self):
        transport = FakeTransport()
        transport.queue_json(200, {"access": "access-token", "refresh": "refresh-token"})
        client = ApiClient("bt", "http://example.test/api", transport=transport)

        client.login("alice", "secret")

        request, body, timeout = transport.calls[0]
        self.assertEqual(request.full_url, "http://example.test/api/token/")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(body.decode("utf-8")), {"username": "alice", "password": "secret"})
        self.assertEqual(client.access_token, "access-token")
        self.assertEqual(client.refresh_token, "refresh-token")
        self.assertEqual(timeout, 5.0)

    def test_get_json_refreshes_token_after_401_and_retries(self):
        transport = FakeTransport()
        transport.queue_error(401)
        transport.queue_json(200, {"access": "new-access"})
        transport.queue_json(200, [{"device_id": 1, "name": "Device"}])
        client = ApiClient("bt", "http://example.test/api", transport=transport)
        client.access_token = "old-access"
        client.refresh_token = "refresh-token"

        data = client.get_json("/devices/")

        self.assertEqual(data, [{"device_id": 1, "name": "Device"}])
        refresh_request = transport.calls[1][0]
        retry_request = transport.calls[2][0]
        self.assertEqual(refresh_request.full_url, "http://example.test/api/token/refresh/")
        self.assertEqual(retry_request.headers["Authorization"], "Bearer new-access")

    def test_refresh_updates_rotated_refresh_token(self):
        transport = FakeTransport()
        transport.queue_json(200, {"access": "new-access", "refresh": "new-refresh"})
        client = ApiClient("bt", "http://example.test/api", transport=transport)
        client.refresh_token = "old-refresh"

        client.refresh_access_token()

        self.assertEqual(client.access_token, "new-access")
        self.assertEqual(client.refresh_token, "new-refresh")

    def test_list_devices_reads_all_paginated_pages(self):
        transport = FakeTransport()
        transport.queue_json(200, {"results": [{"device_id": 1}], "next": "http://example.test/api/devices/?page=2"})
        transport.queue_json(200, {"results": [{"device_id": 2}], "next": None})
        client = ApiClient("bt", "http://example.test/api", transport=transport)
        client.access_token = "access-token"

        devices = client.list_devices()

        self.assertEqual([item["device_id"] for item in devices], [1, 2])
        self.assertEqual(transport.calls[0][0].full_url, "http://example.test/api/devices/")
        self.assertEqual(transport.calls[1][0].full_url, "http://example.test/api/devices/?page=2")

    def test_active_alarms_normalizes_list_response(self):
        transport = FakeTransport()
        transport.queue_json(200, [{"device_id": 1, "alarm_code": 40}])
        client = ApiClient("bt", "http://example.test/api", transport=transport)
        client.access_token = "access-token"

        alarms = client.list_active_alarms()

        self.assertEqual(alarms, [{"device_id": 1, "alarm_code": 40}])


if __name__ == "__main__":
    unittest.main()
