from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class AgentNamingTests(unittest.TestCase):
    def test_tracked_files_do_not_reference_legacy_bt_udp_name(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        legacy_name = "udp" + "_agent"
        file_list = subprocess.check_output(
            ["git", "ls-files", "-z"],
            cwd=repo_root,
        ).decode("utf-8").split("\0")
        offenders: list[str] = []

        for relative_path in file_list:
            if not relative_path:
                continue
            path = repo_root / relative_path
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if legacy_name in text:
                offenders.append(relative_path)

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
