from import_export import fields, resources
from django.utils import timezone

from myapp.models import AnalogData, AlarmData, RelayAction, SwitchData, UserOperation


def _format_dt(value):
    if not value:
        return ""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S.%f")


class SwitchDataCleanupExportResource(resources.ModelResource):
    device__device_id = fields.Field(column_name="设备ID", attribute="device")
    switch_status = fields.Field(column_name="开关量数据包")
    timestamp = fields.Field(column_name="时间", attribute="timestamp")

    class Meta:
        model = SwitchData
        fields = ("timestamp", "device__device_id", "switch_status", "id")
        export_order = ("timestamp", "device__device_id", "switch_status", "id")

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_switch_status(self, obj):
        return obj.get_status_bits_grouped_by_byte(start_byte=4)

    def dehydrate_timestamp(self, obj):
        return _format_dt(obj.timestamp)


class AnalogDataCleanupExportResource(resources.ModelResource):
    device__device_id = fields.Field(column_name="设备ID", attribute="device")
    timestamp = fields.Field(column_name="时间", attribute="timestamp")
    voltage_1 = fields.Field(column_name="电压1(V)", attribute="voltage_1")
    current_1 = fields.Field(column_name="电流1(mA)", attribute="current_1")
    voltage_2 = fields.Field(column_name="电压2(V)", attribute="voltage_2")
    current_2 = fields.Field(column_name="电流2(mA)", attribute="current_2")

    class Meta:
        model = AnalogData
        fields = ("timestamp", "device__device_id", "voltage_1", "current_1", "voltage_2", "current_2", "id")
        export_order = ("timestamp", "device__device_id", "voltage_1", "current_1", "voltage_2", "current_2", "id")

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return _format_dt(obj.timestamp)


class AlarmDataCleanupExportResource(resources.ModelResource):
    device__device_id = fields.Field(column_name="设备ID", attribute="device")
    alarm_code = fields.Field(column_name="告警码", attribute="alarm_code")
    alarm_meaning = fields.Field(column_name="告警含义")
    timestamp_start = fields.Field(column_name="告警开始时间", attribute="timestamp_start")
    timestamp_end = fields.Field(column_name="告警结束时间", attribute="timestamp_end")
    confirmed_status = fields.Field(column_name="确认状态")

    class Meta:
        model = AlarmData
        fields = ("timestamp_start", "timestamp_end", "device__device_id", "alarm_code", "alarm_meaning", "confirmed_status", "id")
        export_order = ("timestamp_start", "timestamp_end", "device__device_id", "alarm_code", "alarm_meaning", "confirmed_status", "id")

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_alarm_meaning(self, obj):
        return obj.alarm_meaning

    def dehydrate_confirmed_status(self, obj):
        return obj.confirmed_status_display()

    def dehydrate_timestamp_start(self, obj):
        return _format_dt(obj.timestamp_start)

    def dehydrate_timestamp_end(self, obj):
        return _format_dt(obj.timestamp_end)


class RelayActionCleanupExportResource(resources.ModelResource):
    device__device_id = fields.Field(column_name="设备ID", attribute="device")
    relay = fields.Field(column_name="继电器", attribute="relay")
    action = fields.Field(column_name="动作", attribute="action")
    timestamp = fields.Field(column_name="时间", attribute="timestamp")

    class Meta:
        model = RelayAction
        fields = ("timestamp", "device__device_id", "relay", "action", "id")
        export_order = ("timestamp", "device__device_id", "relay", "action", "id")

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return _format_dt(obj.timestamp)

    def dehydrate_relay(self, obj):
        return str(obj.relay) if obj.relay is not None else ""

    def dehydrate_action(self, obj):
        return str(obj.action) if obj.action is not None else ""


class UserOperationCleanupExportResource(resources.ModelResource):
    device__device_id = fields.Field(column_name="设备ID", attribute="device")
    function_code = fields.Field(column_name="操作码", attribute="function_code")
    operation = fields.Field(column_name="操作", attribute="operation")
    username = fields.Field(column_name="用户名", attribute="username")
    timestamp = fields.Field(column_name="时间", attribute="timestamp")

    class Meta:
        model = UserOperation
        fields = ("timestamp", "device__device_id", "function_code", "operation", "username", "id")
        export_order = ("timestamp", "device__device_id", "function_code", "operation", "username", "id")

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def dehydrate_username(self, obj):
        return obj.username


CLEANUP_EXPORT_RESOURCE_MAP = {
    SwitchData: SwitchDataCleanupExportResource,
    AnalogData: AnalogDataCleanupExportResource,
    AlarmData: AlarmDataCleanupExportResource,
    RelayAction: RelayActionCleanupExportResource,
    UserOperation: UserOperationCleanupExportResource,
}
