import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QPushButton
except Exception:  # pragma: no cover - allows non-GUI environments to run logic tests
    Qt = None
    QApplication = None

from alarm_client.ui import AlarmPopup, DeviceSelectionDialog


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

    def test_alarm_popup_uses_separate_tables_without_source_column(self):
        dialog = AlarmPopup(lambda: None)
        dialog.set_alerts([
            {
                "system": "bt",
                "source": "current",
                "device_id": 1,
                "device_name": "BT-1",
                "alarm_code": 10,
                "alarm_meaning": "当前测试告警",
                "timestamp": "2026-07-17 10:00:00",
                "timestamp_end": None,
                "confirmed": False,
            },
            {
                "system": "sy",
                "source": "history",
                "device_id": 2,
                "device_name": "SY-2",
                "alarm_code": 20,
                "alarm_meaning": "历史测试告警",
                "timestamp": "2026-07-17 09:00:00",
                "timestamp_end": "2026-07-17 09:30:00",
                "confirmed": False,
            },
        ])

        self.assertEqual(dialog.current_table.rowCount(), 1)
        self.assertEqual(dialog.history_table.rowCount(), 1)
        self.assertEqual(dialog.tabs.count(), 2)
        self.assertEqual(dialog.tabs.currentIndex(), 0)
        self.assertEqual(dialog.tabs.tabText(0), "当前告警（1）")
        self.assertEqual(dialog.tabs.tabText(1), "未确认历史告警（1）")
        self.assertIn("当前 1 条", dialog.summary_label.text())
        self.assertIn("未确认历史 1 条", dialog.summary_label.text())
        current_headers = [
            dialog.current_table.horizontalHeaderItem(column).text()
            for column in range(dialog.current_table.columnCount())
        ]
        history_headers = [
            dialog.history_table.horizontalHeaderItem(column).text()
            for column in range(dialog.history_table.columnCount())
        ]
        self.assertNotIn("来源", current_headers)
        self.assertNotIn("来源", history_headers)
        self.assertNotIn("结束时间", current_headers)
        self.assertIn("结束时间", history_headers)


if __name__ == "__main__":
    unittest.main()
