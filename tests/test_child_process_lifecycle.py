from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import protected_runtime


class _FakeProc:
    def __init__(self, *, poll_value=None, wait_failures: int = 0) -> None:
        self.pid = 12345
        self._poll_value = poll_value
        self._wait_failures = wait_failures
        self.terminated = 0
        self.killed = 0
        self.wait_calls: list[float] = []

    def poll(self):
        return self._poll_value

    def terminate(self) -> None:
        self.terminated += 1

    def kill(self) -> None:
        self.killed += 1

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self._wait_failures > 0:
            self._wait_failures -= 1
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        self._poll_value = 0
        return 0


class ChildProcessLifecycleTests(unittest.TestCase):
    def test_terminate_child_process_skips_already_exited_process(self) -> None:
        proc = _FakeProc(poll_value=0)

        protected_runtime.terminate_child_process(proc)

        self.assertEqual(proc.terminated, 0)
        self.assertEqual(proc.killed, 0)
        self.assertEqual(proc.wait_calls, [])

    def test_terminate_child_process_waits_after_graceful_terminate(self) -> None:
        proc = _FakeProc(poll_value=None)

        protected_runtime.terminate_child_process(proc, terminate_timeout=1.25)

        self.assertEqual(proc.terminated, 1)
        self.assertEqual(proc.killed, 0)
        self.assertEqual(proc.wait_calls, [1.25])

    def test_terminate_child_process_kills_stubborn_windows_process(self) -> None:
        proc = _FakeProc(poll_value=None, wait_failures=1)
        with patch.object(protected_runtime.os, "name", "nt"):
            protected_runtime.terminate_child_process(proc, terminate_timeout=0.1, kill_timeout=0.2)

        self.assertEqual(proc.terminated, 1)
        self.assertEqual(proc.killed, 1)
        self.assertEqual(proc.wait_calls, [0.1, 0.2])

    def test_terminate_child_process_kills_stubborn_posix_process_group(self) -> None:
        proc = _FakeProc(poll_value=None, wait_failures=2)
        with (
            patch.object(protected_runtime.os, "name", "posix"),
            patch.object(protected_runtime.os, "killpg") as killpg,
        ):
            protected_runtime.terminate_child_process(proc, terminate_timeout=0.1, kill_timeout=0.2)

        self.assertEqual(proc.terminated, 1)
        self.assertEqual(proc.killed, 0)
        self.assertEqual(proc.wait_calls, [0.1, 0.2, 0.2])
        self.assertEqual(killpg.call_args_list[0].args, (proc.pid, protected_runtime.signal.SIGTERM))
        self.assertEqual(killpg.call_args_list[1].args, (proc.pid, protected_runtime.signal.SIGKILL))

    def test_bt_agent_ui_stop_agent_uses_terminating_helper(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / "bt_agent" / "bt_agent_ui.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        stop_agent = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "stop_agent"
        )
        helper_calls = [
            node
            for node in ast.walk(stop_agent)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "terminate_child_process"
        ]
        self.assertEqual(len(helper_calls), 1)


if __name__ == "__main__":
    unittest.main()
