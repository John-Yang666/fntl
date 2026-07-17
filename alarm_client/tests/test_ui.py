import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QPushButton
except Exception:  # pragma: no cover - allows non-GUI environments to run logic tests
    Qt = None
    QApplication = None

from alarm_client.ui import DeviceSelectionDialog


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class DeviceSelectionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_server_selection_keeps_all_devices_unchecked(self):
        dialog = DeviceSelectionDialog(
            {
                "bt": [{"device_id": 1, "name": "BT-1"}],
                "sy": [{"device_id": 8, "name": "SY-8"}],
            },
            selected_devices=set(),
        )

        self.assertEqual(dialog.windowTitle(), "选择需要监控的设备")
        self.assertIn("来自服务器", dialog.hint_label.text())
        self.assertEqual(dialog.selected_keys(), set())

        for root_index in range(dialog.tree.topLevelItemCount()):
            root = dialog.tree.topLevelItem(root_index)
            for child_index in range(root.childCount()):
                self.assertEqual(root.child(child_index).checkState(0), Qt.CheckState.Unchecked)

    def test_system_checkbox_toggles_children_and_tracks_partial_state(self):
        dialog = DeviceSelectionDialog(
            {
                "bt": [
                    {"device_id": 1, "name": "BT-1"},
                    {"device_id": 2, "name": "BT-2"},
                ],
                "sy": [],
            },
            selected_devices={"bt:1"},
        )
        bt_root = dialog.tree.topLevelItem(0)

        self.assertEqual(bt_root.checkState(0), Qt.CheckState.PartiallyChecked)

        bt_root.setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(dialog.selected_keys(), {"bt:1", "bt:2"})
        self.assertEqual(bt_root.child(0).checkState(0), Qt.CheckState.Checked)
        self.assertEqual(bt_root.child(1).checkState(0), Qt.CheckState.Checked)

        bt_root.setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(dialog.selected_keys(), set())
        self.assertEqual(bt_root.child(0).checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual(bt_root.child(1).checkState(0), Qt.CheckState.Unchecked)

        bt_root.child(0).setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(bt_root.checkState(0), Qt.CheckState.PartiallyChecked)

    def test_device_dialog_uses_save_cancel_buttons_without_clear_selection(self):
        dialog = DeviceSelectionDialog(
            {
                "bt": [{"device_id": 1, "name": "BT-1"}],
                "sy": [],
            },
            selected_devices={"bt:1"},
        )

        button_texts = {button.text() for button in dialog.findChildren(QPushButton)}

        self.assertIn("保存", button_texts)
        self.assertIn("取消", button_texts)
        self.assertNotIn("OK", button_texts)
        self.assertNotIn("Cancel", button_texts)
        self.assertNotIn("清空选择", button_texts)


if __name__ == "__main__":
    unittest.main()
