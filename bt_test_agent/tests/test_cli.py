from types import SimpleNamespace
import unittest
from unittest import mock

from bt_test_agent import cli


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


class BtCliCleanupTests(unittest.TestCase):
    def test_success_cleans_database_packet_stream_and_command_stream(self):
        args = SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            redis_host="127.0.0.1",
            redis_port=36379,
            packet_stream="stream:udp:packets",
            cmd_stream="stream:udp:cmd",
            username="admin",
            password="admin",
            http_transport="host",
            compose_service="web",
            receiver_cache_wait=2.0,
            timeout=0.1,
            compose_file="docker-compose.yml",
            keep_on_fail=False,
        )
        redis_client = FakeRedis()

        with mock.patch.object(cli, "_connect_redis", return_value=redis_client), \
            mock.patch.object(cli, "HttpClient", FakeHttpClient), \
            mock.patch.object(cli, "prepare_data") as prepare_data, \
            mock.patch.object(cli, "cleanup_data") as cleanup_data, \
            mock.patch.object(cli, "latest_stream_id", return_value="20-0"), \
            mock.patch.object(cli, "xadd_packet", side_effect=[b"pkt-1", b"pkt-2", b"pkt-3"]), \
            mock.patch.object(cli, "find_stream_entry", return_value=(b"cmd-1", {b"payload": b"\x01"})), \
            mock.patch.object(cli, "wait_until"), \
            mock.patch.object(cli.time, "sleep") as sleep:
            self.assertEqual(cli.run(args), 0)

        prepare_data.assert_called_once_with("docker-compose.yml")
        sleep.assert_called_once_with(2.0)
        cleanup_data.assert_called_once_with("docker-compose.yml")
        self.assertIn(("stream:udp:packets", b"pkt-1", b"pkt-2", b"pkt-3"), redis_client.xdel_calls)
        self.assertIn(("stream:udp:cmd", b"cmd-1"), redis_client.xdel_calls)

    def test_parser_accepts_receiver_cache_wait(self):
        args = cli.build_parser().parse_args(["--receiver-cache-wait", "65"])

        self.assertEqual(args.receiver_cache_wait, 65.0)


if __name__ == "__main__":
    unittest.main()
