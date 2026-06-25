import json
import unittest
from unittest import mock

from sy_test_agent.cli import HttpClient


class HttpClientComposeTransportTests(unittest.TestCase):
    def test_compose_transport_executes_request_inside_web_container(self):
        completed = subprocess_result(stdout='{"access":"token"}\n')
        with mock.patch("sy_test_agent.cli.subprocess.run", return_value=completed) as run:
            client = HttpClient(
                "http://127.0.0.1:8000",
                "admin",
                "admin",
                transport="compose",
                compose_file="docker-compose-sy-prod.yml",
            )
            payload = client.post_json("/api/token/", {"username": "admin", "password": "admin"}, auth=False)

        self.assertEqual(payload["access"], "token")
        command = run.call_args.args[0]
        self.assertEqual(command[:7], ["docker", "compose", "-f", "docker-compose-sy-prod.yml", "exec", "-T", "web"])
        request_spec = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request_spec["method"], "POST")
        self.assertEqual(request_spec["url"], "http://127.0.0.1:8000/api/token/")
        self.assertEqual(request_spec["payload"], {"username": "admin", "password": "admin"})


def subprocess_result(stdout="", stderr="", returncode=0):
    return mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)


if __name__ == "__main__":
    unittest.main()
