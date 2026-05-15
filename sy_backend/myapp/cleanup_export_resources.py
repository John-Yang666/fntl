from import_export import fields, resources
from django.utils import timezone

from myapp.models import AlarmData, ChangeBitEvent, RawFrameLog, RelayAction, SwitchData, UserOperation


def _format_dt(value):
    if not value:
        return ""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S.%f")


class RawFrameLogCleanupExportResource(resources.ModelResource):
    id = fields.Field(column_name="ID", attribute="id")
    device = fields.Field(column_name="设备ID", attribute="device")
    cmd = fields.Field(column_name="命令字", attribute="cmd")
    timestamp = fields.Field(column_name="时间", attribute="timestamp")
    note = fields.Field(column_name="备注", attribute="note")
    raw_frame = fields.Field(column_name="HEX帧", attribute="raw_frame")

    class Meta:
        model = RawFrameLog
        fields = ("id", "device", "cmd", "timestamp", "note", "raw_frame")
        export_order = ("id", "device", "cmd", "timestamp", "note", "raw_frame")

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return _format_dt(obj.timestamp)

    def dehydrate_raw_frame(self, obj):
        if not obj.raw_frame:
            return ""
        return bytes(obj.raw_frame).hex().upper()


class SwitchDataCleanupExportResource(resources.ModelResource):
    class Meta:
        model = SwitchData
        fields = ("id", "timestamp", "device", "switch_status")
        export_order = ("id", "timestamp", "device", "switch_status")

    def dehydrate_timestamp(self, obj):
        return _format_dt(obj.timestamp)

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_switch_status(self, obj):
        data = obj.switch_status
        if not data:
            return ""
        return bytes(data).hex().upper()


class ChangeBitEventCleanupExportResource(resources.ModelResource):
    id = fields.Field(column_name="ID", attribute="id")
    device = fields.Field(column_name="设备ID", attribute="device")
    bit_index = fields.Field(column_name="位序号", attribute="bit_index")
    value = fields.Field(column_name="值", attribute="value")
    source = fields.Field(column_name="来源", attribute="source")
    timestamp = fields.Field(column_name="时间", attribute="timestamp")

    class Meta:
        model = ChangeBitEvent
        fields = ("id", "timestamp", "device", "bit_index", "value", "source")
        export_order = ("id", "timestamp", "device", "bit_index", "value", "source")

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return _format_dt(obj.timestamp)


class AlarmDataCleanupExportResource(resources.ModelResource):
    id = fields.Field(column_name="ID", attribute="id")
    device = fields.Field(column_name="设备ID", attribute="device")
    alarm_code = fields.Field(column_name="告警码", attribute="alarm_code")
    alarm_meaning = fields.Field(column_name="告警含义")
    timestamp_start = fields.Field(column_name="告警开始时间", attribute="timestamp_start")
    timestamp_end = fields.Field(column_name="告警结束时间", attribute="timestamp_end")
    is_confirmed = fields.Field(column_name="确认状态", attribute="is_confirmed")

    class Meta:
        model = AlarmData
        fields = ("id", "device", "alarm_code", "alarm_meaning", "timestamp_start", "timestamp_end", "is_confirmed")
        export_order = ("id", "device", "alarm_code", "alarm_meaning", "timestamp_start", "timestamp_end", "is_confirmed")

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_alarm_meaning(self, obj):
        return obj.alarm_meaning

    def dehydrate_timestamp_start(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime("%Y-%m-%d %H:%M:%S")

    def dehydrate_timestamp_end(self, obj):
        if not obj.timestamp_end:
            return ""
        return timezone.localtime(obj.timestamp_end).strftime("%Y-%m-%d %H:%M:%S")

    def dehydrate_is_confirmed(self, obj):
        return obj.confirmed_status_display()


class RelayActionCleanupExportResource(resources.ModelResource):
    id = fields.Field(column_name="ID", attribute="id")
    device = fields.Field(column_name="设备ID", attribute="device")
    relay = fields.Field(column_name="继电器", attribute="relay")
    action = fields.Field(column_name="动作", attribute="action")
    source = fields.Field(column_name="来源", attribute="source")
    timestamp = fields.Field(column_name="时间", attribute="timestamp")

    class Meta:
        model = RelayAction
        fields = ("id", "timestamp", "device", "relay", "action", "source")
        export_order = ("id", "timestamp", "device", "relay", "action", "source")

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return _format_dt(obj.timestamp)


class UserOperationCleanupExportResource(resources.ModelResource):
    id = fields.Field(column_name="ID", attribute="id")
    device = fields.Field(column_name="设备ID", attribute="device")
    function_code = fields.Field(column_name="操作类型", attribute="function_code")
    operation = fields.Field(column_name="操作名称", attribute="operation")
    username = fields.Field(column_name="用户名", attribute="username")
    timestamp = fields.Field(column_name="操作时间", attribute="timestamp")

    class Meta:
        model = UserOperation
        fields = ("id", "device", "function_code", "operation", "username", "timestamp")
        export_order = ("id", "device", "function_code", "operation", "username", "timestamp")

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime("%Y-%m-%d %H:%M:%S")


CLEANUP_EXPORT_RESOURCE_MAP = {
    RawFrameLog: RawFrameLogCleanupExportResource,
    SwitchData: SwitchDataCleanupExportResource,
    ChangeBitEvent: ChangeBitEventCleanupExportResource,
    AlarmData: AlarmDataCleanupExportResource,
    RelayAction: RelayActionCleanupExportResource,
    UserOperation: UserOperationCleanupExportResource,
}
