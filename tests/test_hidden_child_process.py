from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

import protected_runtime


class _FakeStartupInfo:
    def __init__(self) -> None:
        self.dwFlags = 0
        self.wShowWindow = None


class _FakeSubprocess:
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000
    STARTF_USESHOWWINDOW = 0x00000001
    SW_HIDE = 0
    STARTUPINFO = _FakeStartupInfo


class HiddenChildProcessTests(unittest.TestCase):
    def test_windows_child_process_kwargs_hide_console_window(self) -> None:
        with (
            patch.object(protected_runtime.os, "name", "nt"),
            patch.object(protected_runtime, "subprocess", _FakeSubprocess),
        ):
            kwargs = protected_runtime.child_process_popen_kwargs()

        self.assertNotIn("start_new_session", kwargs)
        self.assertEqual(
            kwargs["creationflags"],
            _FakeSubprocess.CREATE_NEW_PROCESS_GROUP | _FakeSubprocess.CREATE_NO_WINDOW,
        )
        self.assertEqual(kwargs["startupinfo"].dwFlags, _FakeSubprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(kwargs["startupinfo"].wShowWindow, _FakeSubprocess.SW_HIDE)

    def test_non_windows_child_process_kwargs_start_new_session(self) -> None:
        with patch.object(protected_runtime.os, "name", "posix"):
            kwargs = protected_runtime.child_process_popen_kwargs()

        self.assertEqual(kwargs, {"start_new_session": True})

    def test_bt_agent_ui_start_agent_uses_hidden_child_process_kwargs(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / "bt_agent" / "bt_agent_ui.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        start_agent_functions = [
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "start_agent"
        ]
        self.assertEqual(len(start_agent_functions), 1)

        popen_calls = [
            node
            for node in ast.walk(start_agent_functions[0])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Popen"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
        ]
        self.assertEqual(len(popen_calls), 1)

        helper_expansions = [
            keyword
            for keyword in popen_calls[0].keywords
            if keyword.arg is None
            and isinstance(keyword.value, ast.Call)
            and isinstance(keyword.value.func, ast.Name)
            and keyword.value.func.id == "child_process_popen_kwargs"
        ]
        self.assertEqual(len(helper_expansions), 1)


if __name__ == "__main__":
    unittest.main()
