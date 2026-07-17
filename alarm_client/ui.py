from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from alarm_client.state import AppConfig, Credentials, SYSTEM_LABELS, SYSTEMS, SystemConfig


class LoginDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("告警客户端登录")
        self.setMinimumWidth(420)
        self.username_edit = QLineEdit(config.credentials.username)
        self.password_edit = QLineEdit(config.credentials.password)
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.bt_api_edit = QLineEdit(config.systems["bt"].api_base)
        self.sy_api_edit = QLineEdit(config.systems["sy"].api_base)
        self.remember_checkbox = QCheckBox("保存账号密码")
        self.remember_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("用户名", self.username_edit)
        form.addRow("密码", self.password_edit)
        form.addRow("BT 前端 API", self.bt_api_edit)
        form.addRow("SY 前端 API", self.sy_api_edit)
        form.addRow("", self.remember_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def build_config(self, base: AppConfig) -> AppConfig:
        config = AppConfig(
            systems={
                "bt": SystemConfig(self.bt_api_edit.text().strip().rstrip("/") or base.systems["bt"].api_base),
                "sy": SystemConfig(self.sy_api_edit.text().strip().rstrip("/") or base.systems["sy"].api_base),
            },
            credentials=Credentials(
                username=self.username_edit.text().strip(),
                password=self.password_edit.text() if self.remember_checkbox.isChecked() else "",
            ),
        )
        return config

    def login_credentials(self) -> Credentials:
        return Credentials(username=self.username_edit.text().strip(), password=self.password_edit.text())


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("接口设置")
        self.setMinimumWidth(420)
        self.bt_api_edit = QLineEdit(config.systems["bt"].api_base)
        self.sy_api_edit = QLineEdit(config.systems["sy"].api_base)

        form = QFormLayout()
        form.addRow("BT 前端 API", self.bt_api_edit)
        form.addRow("SY 前端 API", self.sy_api_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def apply_to(self, config: AppConfig) -> AppConfig:
        config.systems["bt"].api_base = self.bt_api_edit.text().strip().rstrip("/") or config.systems["bt"].api_base
        config.systems["sy"].api_base = self.sy_api_edit.text().strip().rstrip("/") or config.systems["sy"].api_base
        return config


class DeviceSelectionDialog(QDialog):
    def __init__(
        self,
        devices_by_system: dict[str, list[dict[str, Any]]],
        selected_devices: set[str],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("选择需要监控的设备")
        self.setMinimumSize(520, 560)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["设备", "ID"])
        self._updating_tree_checks = False
        for system in SYSTEMS:
            root = QTreeWidgetItem([SYSTEM_LABELS[system], ""])
            root.setFlags(root.flags() | Qt.ItemIsUserCheckable)
            root.setCheckState(0, Qt.Unchecked)
            for device in devices_by_system.get(system, []):
                device_id = device.get("device_id")
                key = f"{system}:{device_id}"
                label = str(device.get("name") or device.get("device_name") or f"设备 {device_id}")
                child = QTreeWidgetItem([label, str(device_id)])
                child.setData(0, Qt.UserRole, key)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked if key in selected_devices else Qt.Unchecked)
                root.addChild(child)
            root.setExpanded(True)
            self.tree.addTopLevelItem(root)
            self._sync_root_check_state(root)
        self.tree.itemChanged.connect(self._on_tree_item_changed)

        self.hint_label = QLabel("当前选择来自服务器，保存后网页端和告警客户端同时生效。")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.tree)
        layout.addWidget(buttons)

    def selected_keys(self) -> set[str]:
        selected: set[str] = set()
        for root_index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(root_index)
            for child_index in range(root.childCount()):
                child = root.child(child_index)
                if child.checkState(0) == Qt.Checked:
                    selected.add(str(child.data(0, Qt.UserRole)))
        return selected

    def clear_selection(self) -> None:
        for root_index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(root_index)
            for child_index in range(root.childCount()):
                root.child(child_index).setCheckState(0, Qt.Unchecked)
            self._sync_root_check_state(root)

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self._updating_tree_checks:
            return
        parent = item.parent()
        if parent is None:
            self._set_children_check_state(item, item.checkState(0))
            return
        self._sync_root_check_state(parent)

    def _set_children_check_state(self, root: QTreeWidgetItem, state: Qt.CheckState) -> None:
        self._updating_tree_checks = True
        try:
            target_state = Qt.Checked if state != Qt.Unchecked else Qt.Unchecked
            for child_index in range(root.childCount()):
                root.child(child_index).setCheckState(0, target_state)
            root.setCheckState(0, target_state)
        finally:
            self._updating_tree_checks = False

    def _sync_root_check_state(self, root: QTreeWidgetItem) -> None:
        if root.childCount() == 0:
            return
        checked_count = sum(
            1 for child_index in range(root.childCount())
            if root.child(child_index).checkState(0) == Qt.Checked
        )
        if checked_count == 0:
            state = Qt.Unchecked
        elif checked_count == root.childCount():
            state = Qt.Checked
        else:
            state = Qt.PartiallyChecked

        self._updating_tree_checks = True
        try:
            root.setCheckState(0, state)
        finally:
            self._updating_tree_checks = False


class AlarmPopup(QDialog):
    def __init__(self, on_closed: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.on_closed = on_closed
        self._closing_programmatically = False
        self.setWindowTitle("告警详情")
        self.setMinimumSize(760, 360)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self.summary_label = QLabel("告警详情")
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["系统", "来源", "设备ID", "设备名称", "告警码", "告警含义", "开始时间", "结束时间", "确认状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        close_button = QPushButton("关闭本窗口并暂停告警声")
        close_button.clicked.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)
        layout.addWidget(close_button)

    def set_alerts(self, alerts: list[dict[str, Any]]) -> None:
        self.summary_label.setText(f"告警详情 {len(alerts)} 条")
        self.table.setRowCount(len(alerts))
        for row, alert in enumerate(alerts):
            values = [
                SYSTEM_LABELS.get(str(alert.get("system")), str(alert.get("system", ""))).upper(),
                "当前" if alert.get("source") == "current" else "历史",
                str(alert.get("device_id", "")),
                str(alert.get("device_name", "")),
                str(alert.get("alarm_code", "")),
                str(alert.get("alarm_meaning", "")),
                str(alert.get("timestamp", "")),
                str(alert.get("timestamp_end") or "—"),
                "已确认" if bool(alert.get("confirmed")) else "未确认",
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def show_alerts(self, alerts: list[dict[str, Any]]) -> None:
        self.set_alerts(alerts)
        self.show()
        self.raise_()
        self.activateWindow()

    def close_without_pause(self) -> None:
        self._closing_programmatically = True
        try:
            self.close()
        finally:
            self._closing_programmatically = False

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._closing_programmatically:
            self.on_closed()
        super().closeEvent(event)


def show_error(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)
