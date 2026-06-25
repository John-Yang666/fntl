import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


class DockerTestAgentScriptTests(unittest.TestCase):
    def _run_with_fake_tools(self, script_name: str, prod_compose: str):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "calls.log"
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()

            docker_script = fake_bin / "docker"
            docker_script.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    printf 'DOCKER %s\\n' "$*" >> {str(log_path)!r}
                    if [[ "$*" == "compose -f docker-compose.yml ps --status running --services" ]]; then
                      exit 0
                    fi
                    if [[ "$*" == "compose -f docker-compose-sy.yml ps --status running --services" ]]; then
                      exit 0
                    fi
                    if [[ "$*" == "compose -f {prod_compose} ps --status running --services" ]]; then
                      printf 'web\\nredis_stream\\nudp_receiver\\nsy_receiver\\nsummarize_alarms_container\\n'
                      exit 0
                    fi
                    if [[ "$*" == "compose -f {prod_compose} exec -T redis_stream redis-cli ping" ]]; then
                      printf 'PONG\\n'
                      exit 0
                    fi
                    if [[ "$*" == compose\\ -f\\ {prod_compose}\\ exec\\ -T\\ web\\ python\\ -* ]]; then
                      cat >/dev/null
                      printf '{{"access":"fake"}}\\n'
                      exit 0
                    fi
                    printf 'unexpected docker call: %s\\n' "$*" >&2
                    exit 9
                    """
                ),
                encoding="utf-8",
            )
            docker_script.chmod(docker_script.stat().st_mode | stat.S_IXUSR)

            python_script = fake_bin / "python3"
            python_script.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    printf 'PYTHON3 %s\\n' "$*" >> {str(log_path)!r}
                    exit 0
                    """
                ),
                encoding="utf-8",
            )
            python_script.chmod(python_script.stat().st_mode | stat.S_IXUSR)

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            env.pop("BT_TEST_AGENT_COMPOSE_FILE", None)
            env.pop("SY_TEST_AGENT_COMPOSE_FILE", None)
            result = subprocess.run(
                ["bash", str(ROOT_DIR / "scripts" / script_name)],
                cwd=str(ROOT_DIR),
                env=env,
                text=True,
                capture_output=True,
            )
            calls = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            return result, calls

    def test_bt_script_auto_selects_running_prod_stack(self):
        result, calls = self._run_with_fake_tools("run-bt-docker-test-agent.sh", "docker-compose-prod.yml")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PYTHON3 -m bt_test_agent", calls)
        self.assertIn("--compose-file docker-compose-prod.yml", calls)
        self.assertIn("--base-url http://127.0.0.1:8000", calls)
        self.assertIn("--http-transport compose", calls)
        self.assertIn("--receiver-cache-wait 65", calls)

    def test_sy_script_auto_selects_running_prod_stack(self):
        result, calls = self._run_with_fake_tools("run-sy-docker-test-agent.sh", "docker-compose-sy-prod.yml")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PYTHON3 -m sy_test_agent", calls)
        self.assertIn("--compose-file docker-compose-sy-prod.yml", calls)
        self.assertIn("--base-url http://127.0.0.1:8000", calls)
        self.assertIn("--http-transport compose", calls)
        self.assertIn("--receiver-cache-wait 65", calls)


if __name__ == "__main__":
    unittest.main()
