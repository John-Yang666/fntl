from types import SimpleNamespace
import unittest
from unittest import mock

from sy_test_agent import cli


class FakeRedis:
    def __init__(self):
        self.xdel_calls = []

    def xdel(self, *args):
        self.xdel_calls.append(args)


class FakeHttpClient:
    def __init__(self, *args, **kwargs):
        self.posts = []

    def login(self):
        return None

    def post_json(self, path, payload, auth=True):
        self.posts.append((path, payload, auth))
        return {}


class SyCliCleanupTests(unittest.TestCase):
    def test_device_switch_payload_accepts_prod_hex_shape(self):
        self.assertTrue(cli._has_device_switch_data({"timestamp": "now", "version": "v4", "hex": "00100000"}))

    def test_success_cleans_database_raw_stream_and_command_stream(self):
        args = SimpleNamespace(
            base_url="http://127.0.0.1:8001",
            redis_host="127.0.0.1",
            redis_port=36380,
            raw_stream="sy.raw",
            cmd_stream="sy-serial-commands",
            username="admin",
            password="admin",
            http_transport="host",
            compose_service="web",
            receiver_cache_wait=2.0,
            timeout=0.1,
            compose_file="docker-compose-sy.yml",
            keep_on_fail=False,
        )
        redis_client = FakeRedis()

        with mock.patch.object(cli, "_connect_redis", return_value=redis_client), \
            mock.patch.object(cli, "HttpClient", FakeHttpClient), \
            mock.patch.object(cli, "prepare_data") as prepare_data, \
            mock.patch.object(cli, "cleanup_data") as cleanup_data, \
            mock.patch.object(cli, "latest_stream_id", return_value="20-0"), \
            mock.patch.object(cli, "xadd_raw", side_effect=["raw-1", "raw-2"]), \
            mock.patch.object(
                cli,
                "find_stream_entry",
                return_value=("cmd-1", {"data": '{"device_id": 9201, "command": "BB", "frame_hex": "7f7ff1bbf7"}'}),
            ), \
            mock.patch.object(cli, "wait_until"), \
            mock.patch.object(cli.time, "sleep") as sleep:
            self.assertEqual(cli.run(args), 0)

        prepare_data.assert_called_once_with("docker-compose-sy.yml")
        sleep.assert_called_once_with(2.0)
        cleanup_data.assert_called_once_with("docker-compose-sy.yml")
        self.assertIn(("sy.raw", "raw-1", "raw-2"), redis_client.xdel_calls)
        self.assertIn(("sy-serial-commands", "cmd-1"), redis_client.xdel_calls)

    def test_parser_accepts_receiver_cache_wait(self):
        args = cli.build_parser().parse_args(["--receiver-cache-wait", "65"])

        self.assertEqual(args.receiver_cache_wait, 65.0)


if __name__ == "__main__":
    unittest.main()
