from pathlib import Path
import tempfile
import unittest

from myproject.deploy_host_settings import (
    build_allowed_hosts,
    build_cors_allowed_origins,
    read_deploy_host_list,
)


class DeployHostSettingsTests(unittest.TestCase):
    def test_deploy_host_file_extends_allowed_hosts_and_cors_origins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            deploy_host_file = Path(temp_dir) / "deploy_host_ip.txt"
            deploy_host_file.write_text(
                "# comment\n"
                "192.168.0.87\n"
                "192.168.0.88; 192.168.0.89\n"
                "http://192.168.0.90:38173/runtime-config\n",
                encoding="utf-8",
            )

            deploy_hosts = read_deploy_host_list(deploy_host_file)
            allowed_hosts = build_allowed_hosts(
                ["localhost", "127.0.0.1", "bt_nms_django_app"],
                deploy_hosts,
            )
            cors_origins = build_cors_allowed_origins(
                ["http://localhost:38173"],
                deploy_hosts,
                http_ports=(38173,),
                https_ports=(38443,),
            )

        self.assertEqual(
            deploy_hosts,
            [
                "192.168.0.87",
                "192.168.0.88",
                "192.168.0.89",
                "http://192.168.0.90:38173/runtime-config",
            ],
        )
        self.assertEqual(
            allowed_hosts,
            [
                "localhost",
                "127.0.0.1",
                "bt_nms_django_app",
                "192.168.0.87",
                "192.168.0.88",
                "192.168.0.89",
                "192.168.0.90",
            ],
        )
        self.assertIn("http://localhost:38173", cors_origins)
        self.assertIn("http://192.168.0.87:38173", cors_origins)
        self.assertIn("https://192.168.0.87:38443", cors_origins)
        self.assertIn("http://192.168.0.88:38173", cors_origins)
        self.assertIn("http://192.168.0.89:38173", cors_origins)
        self.assertIn("http://192.168.0.90:38173", cors_origins)
        self.assertIn("https://192.168.0.90:38443", cors_origins)
        self.assertNotIn("http://192.168.0.90:38173/runtime-config", cors_origins)


if __name__ == "__main__":
    unittest.main()
