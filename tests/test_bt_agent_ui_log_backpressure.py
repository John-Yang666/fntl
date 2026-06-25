from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = REPO_ROOT / "bt_agent" / "bt_agent_ui.py"
AGENT_SOURCE = REPO_ROOT / "bt_agent" / "bt_agent.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


class BtAgentUiLogBackpressureTests(unittest.TestCase):
    def test_log_queue_has_explicit_max_size(self) -> None:
        tree = _parse(UI_SOURCE)
        queue_assignments = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and target.attr == "_log_queue"
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                for target in node.targets
            )
            and isinstance(node.value, ast.Call)
        ]

        self.assertEqual(len(queue_assignments), 1)
        kwargs = {keyword.arg: keyword.value for keyword in queue_assignments[0].value.keywords}
        self.assertIn("maxsize", kwargs)
        self.assertIsInstance(kwargs["maxsize"], ast.Name)
        self.assertEqual(kwargs["maxsize"].id, "LOG_QUEUE_MAXSIZE")

    def test_log_queue_poll_is_bounded_per_timer_tick(self) -> None:
        tree = _parse(UI_SOURCE)
        poll_log_queue = _function(tree, "_poll_log_queue")
        bounded_loops = [
            node
            for node in ast.walk(poll_log_queue)
            if isinstance(node, ast.For)
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
            and len(node.iter.args) == 1
            and isinstance(node.iter.args[0], ast.Name)
            and node.iter.args[0].id == "LOG_QUEUE_DRAIN_LIMIT"
        ]
        unbounded_loops = [
            node
            for node in ast.walk(poll_log_queue)
            if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True
        ]

        self.assertEqual(len(bounded_loops), 1)
        self.assertEqual(unbounded_loops, [])

    def test_child_output_uses_nonblocking_bounded_enqueue(self) -> None:
        tree = _parse(UI_SOURCE)
        enqueue = _function(tree, "_enqueue_log_event")
        read_child_output = _function(tree, "_read_child_output")

        put_nowait_calls = [
            node
            for node in ast.walk(enqueue)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "put_nowait"
        ]
        direct_queue_puts = [
            node
            for node in ast.walk(read_child_output)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"put", "put_nowait"}
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "_log_queue"
        ]

        self.assertGreaterEqual(len(put_nowait_calls), 1)
        self.assertEqual(direct_queue_puts, [])

    def test_valid_packet_logs_are_not_info_level(self) -> None:
        source = AGENT_SOURCE.read_text(encoding="utf-8")

        self.assertNotIn('logger.info(f"收到来自', source)
        self.assertNotIn('logger.info(f"Received analog data', source)
        self.assertIn('logger.debug(f"收到来自', source)
        self.assertIn('logger.debug(f"Received analog data', source)


if __name__ == "__main__":
    unittest.main()
