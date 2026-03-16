# admin.py  —— sy 设备网管版（20251218 优化导出功能：避免 stdout/对象/memoryview 混淆）
import json
import os
import binascii
import logging
import time

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import format_html

import redis
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import JSONWidget, BooleanWidget, ManyToManyWidget, IntegerWidget, FloatWidget

from django_admin_filters import DateRange
import redis

from .models import (
    Device, SwitchData, ChangeBitEvent, RawFrameLog,
    AlarmActive, AlarmData,
    RelayAction, UserOperation, UploadedFile,
)

logger = logging.getLogger(__name__)


# ========================
# 通用权限过滤基类
# ========================
class DepotScopedAdmin(admin.ModelAdmin):
    """
    根据 user.depots 限制数据范围。
    子类可通过 depot_filter_field 指定字段路径，例如 'device__depot'。
    """
    depot_filter_field = 'depot'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user

        if user.is_superuser:
            return qs

        depots = getattr(user, 'depots', None)
        if isinstance(depots, list) and depots:
            return qs.filter(**{f"{self.depot_filter_field}__in": depots})

        return qs.none()


# ========================
# 公共批量动作
# ========================
def batch_confirm(modeladmin, request, queryset):
    """批量确认告警"""
    updated_count = queryset.update(is_confirmed=True)
    modeladmin.message_user(request, f"成功确认 {updated_count} 条告警。", level=messages.SUCCESS)
batch_confirm.short_description = "确认选中的告警"


def batch_delete(modeladmin, request, queryset):
    """批量强制删除（分批避免大事务）"""
    batch_size = 1000
    iterator = queryset.iterator()
    deleted_count = 0
    while True:
        ids = []
        for _ in range(batch_size):
            try:
                ids.append(next(iterator).id)
            except StopIteration:
                break
        if not ids:
            break
        modeladmin.model.objects.filter(id__in=ids).delete()
        deleted_count += len(ids)

    modeladmin.message_user(request, f'成功删除 {deleted_count} 条记录', level=messages.SUCCESS)
batch_delete.short_description = '强制删除选中的项目'


# ========================
# 自定义时间筛选器
# ========================
class MyDateRangePicker(DateRange):
    WIDGET_LOCALE = 'zh-cn'
    WIDGET_WITH_TIME = True
    FILTER_LABEL = "时间范围"
    ALL_LABEL = '全部'
    CUSTOM_LABEL = "自定义时间格式如下："
    FROM_LABEL = "从"
    TO_LABEL = "到"
    DATE_FORMAT = "YYYY-MM-DD HH:mm \n 例如: 2024-01-01 00:00"
    BUTTON_LABEL = "按上述时间筛选"
    is_null_option = False
    options = (
        ('1da', "24小时之内", 60 * 60 * -24),
        ('1dp', "7天之内", 60 * 60 * -24 * 7),
    )


# ========================
# 当前告警（只导出，不导入，禁止新增）
# ========================
class AlarmActiveResource(resources.ModelResource):
    id = fields.Field(column_name='ID', attribute='id')
    device = fields.Field(column_name='设备ID', attribute='device')
    alarm_code = fields.Field(column_name='告警码', attribute='alarm_code')
    alarm_meaning = fields.Field(column_name='告警含义')
    timestamp_start = fields.Field(column_name='告警开始时间', attribute='timestamp_start')
    is_confirmed = fields.Field(column_name='确认状态', attribute='is_confirmed')

    class Meta:
        model = AlarmActive
        fields = (
            'id',
            'device',
            'alarm_code',
            'alarm_meaning',
            'timestamp_start',
            'is_confirmed',
        )
        export_order = (
            'id',
            'device',
            'alarm_code',
            'alarm_meaning',
            'timestamp_start',
            'is_confirmed',
        )
        import_id_fields = ('id',)

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_alarm_meaning(self, obj):
        return obj.alarm_meaning

    def dehydrate_timestamp_start(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')

    def dehydrate_is_confirmed(self, obj):
        return obj.confirmed_status_display()


@admin.register(AlarmActive)
class AlarmActiveAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = AlarmActiveResource

    list_display = (
        'timestamp_start_display', 'device',
        'alarm_code', 'alarm_meaning', 'show_confirmed_status'
    )
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (
        ('timestamp_start', MyDateRangePicker),
        'device__name', 'device__device_id', 'alarm_code', 'is_confirmed'
    )
    actions = [batch_delete, batch_confirm]

    def has_import_permission(self, request, *args, **kwargs):
        return False

    def has_add_permission(self, request):
        return False

    def alarm_meaning(self, obj):
        return obj.alarm_meaning

    def show_confirmed_status(self, obj):
        return obj.confirmed_status_display()

    def timestamp_start_display(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')

    show_confirmed_status.admin_order_field = 'is_confirmed'
    show_confirmed_status.short_description = '确认状态'
    timestamp_start_display.admin_order_field = 'timestamp_start'
    timestamp_start_display.short_description = '开始时间'


# ========================
# 历史告警（只导出，不导入，禁止新增）
# ========================
class AlarmDataResource(resources.ModelResource):
    id = fields.Field(column_name='ID', attribute='id')
    device = fields.Field(column_name='设备ID', attribute='device')
    alarm_code = fields.Field(column_name='告警码', attribute='alarm_code')
    alarm_meaning = fields.Field(column_name='告警含义')
    timestamp_start = fields.Field(column_name='告警开始时间', attribute='timestamp_start')
    timestamp_end = fields.Field(column_name='告警结束时间', attribute='timestamp_end')
    is_confirmed = fields.Field(column_name='确认状态', attribute='is_confirmed')

    class Meta:
        model = AlarmData
        fields = (
            'id',
            'device',
            'alarm_code',
            'alarm_meaning',
            'timestamp_start',
            'timestamp_end',
            'is_confirmed',
        )
        export_order = (
            'id',
            'device',
            'alarm_code',
            'alarm_meaning',
            'timestamp_start',
            'timestamp_end',
            'is_confirmed',
        )
        import_id_fields = ('id',)

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_alarm_meaning(self, obj):
        return obj.alarm_meaning

    def dehydrate_timestamp_start(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')

    def dehydrate_timestamp_end(self, obj):
        return (
            timezone.localtime(obj.timestamp_end).strftime('%Y-%m-%d %H:%M:%S')
            if obj.timestamp_end else ""
        )

    def dehydrate_is_confirmed(self, obj):
        return obj.confirmed_status_display()


@admin.register(AlarmData)
class AlarmDataAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = AlarmDataResource

    list_display = (
        'timestamp_start_display', 'timestamp_end_display', 'device',
        'alarm_code', 'alarm_meaning', 'show_confirmed_status'
    )
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (
        ('timestamp_start', MyDateRangePicker),
        'device__name', 'device__device_id', 'alarm_code', 'is_confirmed'
    )
    actions = [batch_delete, batch_confirm]

    def has_import_permission(self, request, *args, **kwargs):
        return False

    def has_add_permission(self, request):
        return False

    def alarm_meaning(self, obj):
        return obj.alarm_meaning

    def show_confirmed_status(self, obj):
        return obj.confirmed_status_display()

    def timestamp_start_display(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')

    def timestamp_end_display(self, obj):
        return (
            timezone.localtime(obj.timestamp_end).strftime('%Y-%m-%d %H:%M:%S')
            if obj.timestamp_end else ""
        )

    alarm_meaning.short_description = '告警含义'
    show_confirmed_status.admin_order_field = 'is_confirmed'
    show_confirmed_status.short_description = '确认状态'
    timestamp_start_display.admin_order_field = 'timestamp_start'
    timestamp_start_display.short_description = '开始时间'
    timestamp_end_display.admin_order_field = 'timestamp_end'
    timestamp_end_display.short_description = '结束时间'


# ========================
# 原始协议帧（只导出，不导入，禁止新增）
# ========================
class RawFrameLogResource(resources.ModelResource):
    id = fields.Field(column_name='ID', attribute='id')
    device = fields.Field(column_name='设备ID', attribute='device')
    cmd = fields.Field(column_name='命令字', attribute='cmd')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')
    note = fields.Field(column_name='备注', attribute='note')
    raw_frame = fields.Field(column_name='HEX帧', attribute='raw_frame')

    class Meta:
        model = RawFrameLog
        fields = ('id', 'device', 'cmd', 'timestamp', 'note', 'raw_frame')
        export_order = ('id', 'device', 'cmd', 'timestamp', 'note', 'raw_frame')
        import_id_fields = ('id',)

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

    def dehydrate_raw_frame(self, obj):
        if not obj.raw_frame:
            return ""
        return bytes(obj.raw_frame).hex().upper()


@admin.register(RawFrameLog)
class RawFrameLogAdmin(ImportExportModelAdmin):
    resource_class = RawFrameLogResource

    list_display = ("timestamp_with_seconds", "device_display", "cmd", "raw_hex_short")
    search_fields = ("cmd",)
    list_filter = ("cmd", "device")
    readonly_fields = ("timestamp", "raw_hex_full", "device", "cmd", "note")
    actions = [batch_delete]

    def has_import_permission(self, request, *args, **kwargs):
        return False

    def has_add_permission(self, request):
        return False

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp_with_seconds.short_description = '时间'

    def device_display(self, obj):
        if obj.device:
            return f"Device {obj.device.device_id} - IP: {obj.device.ip_address}"
        return "未解析"
    device_display.short_description = "设备"

    def raw_hex_short(self, obj):
        if not obj.raw_frame:
            return "(空)"
        b = bytes(obj.raw_frame)
        hex_str = b.hex().upper()
        return (hex_str[:40] + "...") if len(hex_str) > 40 else hex_str
    raw_hex_short.short_description = "HEX（短）"

    def raw_hex_full(self, obj):
        if not obj.raw_frame:
            return "(空)"
        hex_str = bytes(obj.raw_frame).hex().upper()
        grouped = " ".join(hex_str[i:i + 2] for i in range(0, len(hex_str), 2))
        return format_html("<pre>{}</pre>", grouped)
    raw_hex_full.short_description = "完整 HEX 帧"


# ========================
# sy 状态字快照（A1 全部量）—— 只导出，不导入，不允许新增
# ========================
class SwitchDataResource(resources.ModelResource):
    class Meta:
        model = SwitchData
        fields = ('id', 'timestamp', 'device', 'switch_status')
        export_order = ('id', 'timestamp', 'device', 'switch_status')
        import_id_fields = ('id',)

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_switch_status(self, obj):
        data = obj.switch_status
        if not data:
            return ""
        return bytes(data).hex().upper()


@admin.register(SwitchData)
class SwitchDataAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = SwitchDataResource

    list_display = ('timestamp_with_seconds', 'device', 'protocol_hex_short')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id')
    search_fields = ('device__device_id', 'device__ip_address', 'device__name')
    actions = [batch_delete]

    def has_import_permission(self, request, *args, **kwargs):
        return False

    def has_add_permission(self, request):
        return False

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp_with_seconds.short_description = '时间'

    def protocol_hex_short(self, obj):
        if not obj.switch_status:
            return ""
        data = bytes(obj.switch_status)
        return binascii.hexlify(data).decode().upper()
    protocol_hex_short.short_description = '状态字HEX'


# ========================
# 变化量事件（A2）（只导出，不导入，禁止新增）
# ========================
class ChangeBitEventResource(resources.ModelResource):
    id = fields.Field(column_name='ID', attribute='id')
    device = fields.Field(column_name='设备ID', attribute='device')
    bit_index = fields.Field(column_name='位序号', attribute='bit_index')
    value = fields.Field(column_name='值', attribute='value')
    source = fields.Field(column_name='来源', attribute='source')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')

    class Meta:
        model = ChangeBitEvent
        fields = ('id', 'timestamp', 'device', 'bit_index', 'value', 'source')
        export_order = ('id', 'timestamp', 'device', 'bit_index', 'value', 'source')
        import_id_fields = ('id',)

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')


@admin.register(ChangeBitEvent)
class ChangeBitEventAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = ChangeBitEventResource

    list_display = ('timestamp_with_seconds', 'device', 'bit_index', 'value', 'source')
    search_fields = ('device__device_id', 'device__name', 'bit_index', 'source')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'source', 'value')
    actions = [batch_delete]

    def has_import_permission(self, request, *args, **kwargs):
        return False

    def has_add_permission(self, request):
        return False

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp_with_seconds.short_description = '时间'


# ========================
# 用户（自定义导入导出）
# ========================
CustomUser = get_user_model()


class CustomUserResource(resources.ModelResource):
    username = fields.Field(attribute='username', column_name='用户名')
    email = fields.Field(attribute='email', column_name='邮箱')
    is_active = fields.Field(attribute='is_active', column_name='是否激活', widget=BooleanWidget())
    is_staff = fields.Field(attribute='is_staff', column_name='是否为管理员', widget=BooleanWidget())
    depots = fields.Field(attribute='depots', column_name='可管理车间', widget=JSONWidget())
    groups = fields.Field(
        attribute='groups',
        column_name='用户组',
        widget=ManyToManyWidget(Group, field='name', separator=', ')
    )
    user_permissions = fields.Field(
        attribute='user_permissions',
        column_name='用户权限',
        widget=ManyToManyWidget(Permission, field='codename', separator=', ')
    )

    class Meta:
        model = CustomUser
        import_id_fields = ['username']
        fields = ('username', 'email', 'is_active', 'is_staff', 'depots', 'groups', 'user_permissions')
        export_order = ('username', 'email', 'is_active', 'is_staff', 'depots', 'groups', 'user_permissions')

    def before_import_row(self, row, row_number=None, **kwargs):
        if not row.get('可管理车间'):
            row['可管理车间'] = '[]'

        group_names = [g.strip() for g in (row.get('用户组') or '').split(',') if g.strip()]
        for group_name in group_names:
            if not Group.objects.filter(name=group_name).exists():
                raise ValidationError(f'第 {row_number} 行错误：用户组 "{group_name}" 不存在，请先在后台创建。')

        perm_codenames = [p.strip() for p in (row.get('用户权限') or '').split(',') if p.strip()]
        for codename in perm_codenames:
            if not Permission.objects.filter(codename=codename).exists():
                raise ValidationError(f'第 {row_number} 行错误：权限 "{codename}" 不存在。请确认拼写或在后台创建。')


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin, ImportExportModelAdmin):
    resource_class = CustomUserResource
    list_display = ('username', 'email', 'is_staff', 'is_active', 'depots')
    search_fields = ('username', 'email')
    ordering = ('username',)
    fieldsets = UserAdmin.fieldsets + (('车间管理', {'fields': ('depots',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('车间管理', {'fields': ('depots',)}),)

    class Media:
        css = {'all': ('admin/css/widgets.css',)}


# ========================
# 用户操作（只导出，不导入，禁止新增）
# ========================
class UserOperationResource(resources.ModelResource):
    id = fields.Field(column_name='ID', attribute='id')
    device = fields.Field(column_name='设备ID', attribute='device')
    function_code = fields.Field(column_name='操作类型', attribute='function_code')
    operation = fields.Field(column_name='操作名称', attribute='operation')
    username = fields.Field(column_name='用户名', attribute='username')
    timestamp = fields.Field(column_name='操作时间', attribute='timestamp')

    class Meta:
        model = UserOperation
        fields = ('id', 'device', 'function_code', 'operation', 'username', 'timestamp')
        export_order = ('id', 'device', 'function_code', 'operation', 'username', 'timestamp')
        import_id_fields = ('id',)

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S')


@admin.register(UserOperation)
class UserOperationAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = UserOperationResource

    list_display = ('id', 'device', 'function_code', 'operation', 'username', 'timestamp_with_seconds')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'function_code', 'operation', 'username')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'operation', 'username')
    actions = [batch_delete]

    def has_import_permission(self, request, *args, **kwargs):
        return False

    def has_add_permission(self, request):
        return False

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S')
    timestamp_with_seconds.short_description = '操作时间'


# ========================
# 继电器动作（只导出，不导入，禁止新增）
# ========================
class RelayActionResource(resources.ModelResource):
    id = fields.Field(column_name='ID', attribute='id')
    device = fields.Field(column_name='设备ID', attribute='device')
    relay = fields.Field(column_name='继电器', attribute='relay')
    action = fields.Field(column_name='动作', attribute='action')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')

    class Meta:
        model = RelayAction
        fields = ('id', 'timestamp', 'device', 'relay', 'action')
        export_order = ('id', 'timestamp', 'device', 'relay', 'action')
        import_id_fields = ('id',)

    def dehydrate_device(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')


@admin.register(RelayAction)
class RelayActionAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = RelayActionResource

    list_display = ('timestamp_with_seconds', 'device', 'relay', 'action')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'relay', 'action')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'relay', 'action')
    actions = [batch_delete]

    def has_import_permission(self, request, *args, **kwargs):
        return False

    def has_add_permission(self, request):
        return False

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp_with_seconds.short_description = '时间'


# ========================
# 设备（含导入导出 & 重连动作）
# ========================
import json
import time
import redis

# Streams Redis（独立容器 redis_stream）
STREAM_REDIS_HOST = os.getenv("STREAM_REDIS_HOST", "redis_stream")
STREAM_REDIS_PORT = int(os.getenv("STREAM_REDIS_PORT", "6379"))
UDP_STREAM_DB = int(os.getenv("UDP_STREAM_DB", "0"))
UDP_COMMAND_STREAM = os.getenv("UDP_COMMAND_STREAM", "udp-commands")
UDP_COMMAND_STREAM_MAXLEN = int(os.getenv("UDP_COMMAND_STREAM_MAXLEN", "200000"))

def _forward_wrap(packet: bytes, target_ip: str) -> bytes:
    # 保持你原来的“ip + \\n + packet”格式不变
    return (f"{target_ip}\n").encode("utf-8") + packet


def _build_reconnect_packet_fixed_addr() -> bytes:
    return bytes.fromhex("7F 7F 01 0B 00 00 00 00 00 00 00 00 0C 00 F7 F7")


_stream_client = None


def _get_stream_client() -> redis.Redis:
    global _stream_client
    if _stream_client is None:
        _stream_client = redis.StrictRedis(
            host=STREAM_REDIS_HOST,
            port=STREAM_REDIS_PORT,
            db=UDP_STREAM_DB,
            decode_responses=True,
        )
    return _stream_client


#重连命令为bt网管中的功能，sy中尚未实现该功能，此处代码仅供未来扩展参考
@admin.action(description="对所选设备发送【重连】命令")
def send_reconnect_command(modeladmin, request, queryset):
    r = _get_stream_client()

    ok, fail = 0, 0
    missing_ip = []
    pkt = _build_reconnect_packet_fixed_addr()

    for dev in queryset:
        target_ip = getattr(dev, "ip_address", None)
        if not target_ip:
            missing_ip.append(str(getattr(dev, "device_id", dev.pk)))
            continue

        payload_bytes = _forward_wrap(pkt, target_ip)

        # 统一用 JSON + payload_hex（兼容你之前 Kafka 的 bytes payload 思路）
        msg = {
            "type": "udp_forward",
            "payload_hex": payload_bytes.hex(),
            "ts": int(time.time()),
            "meta": {
                "device_id": getattr(dev, "device_id", dev.pk),
                "ip": target_ip,
                "op": "reconnect",
            },
        }

        try:
            # 按你原来逻辑：发 3 次
            for _ in range(3):
                r.xadd(
                    UDP_COMMAND_STREAM,
                    fields={"data": json.dumps(msg, ensure_ascii=False)},
                    maxlen=UDP_COMMAND_STREAM_MAXLEN,
                    approximate=True,
                )
            ok += 1

            UserOperation.objects.create(
                device=dev,
                function_code="0B",
                operation=f"发送重连命令到 {target_ip}",
                username=request.user.username,
            )

        except Exception:
            fail += 1
            logger.exception(
                "[ADMIN reconnect] device=%s ip=%s send failed",
                getattr(dev, "device_id", dev.pk),
                target_ip,
            )

    if ok:
        messages.success(request, f"已向 {ok} 台设备发送【重连】命令，并记录操作日志。")
    if fail:
        messages.error(request, f"{fail} 台设备发送失败，详见服务器日志。")
    if missing_ip:
        messages.warning(request, f"以下设备未配置 IP，已跳过：{', '.join(missing_ip)}")


CANON_DEVICE_ID_COL = "设备ID"

def _norm_header(h) -> str:
    if h is None:
        return ""
    return str(h).replace("\ufeff", "").strip()

class NullableIntegerWidget(IntegerWidget):
    def clean(self, value, row=None, *args, **kwargs):
        if value is None:
            return None
        if isinstance(value, str) and value.strip() in ("", "none", "null", "nan", "None", "NULL", "NaN"):
            return None
        return super().clean(value, row=row, *args, **kwargs)

class NullableFloatWidget(FloatWidget):
    def clean(self, value, row=None, *args, **kwargs):
        if value is None:
            return None
        if isinstance(value, str) and value.strip() in ("", "none", "null", "nan", "None", "NULL", "NaN"):
            return None
        return super().clean(value, row=row, *args, **kwargs)

class DeviceResource(resources.ModelResource):
    # ★★ 关键：id 只导出不导入（避免把主键改掉导致插入新行）
    id = fields.Field(column_name='id', attribute='id', readonly=True)

    # --- 基本信息 ---
    device_id = fields.Field(column_name=CANON_DEVICE_ID_COL, attribute='device_id', widget=NullableIntegerWidget())
    name = fields.Field(column_name='设备名称', attribute='name')
    depot = fields.Field(column_name='车间', attribute='depot')
    line = fields.Field(column_name='线路', attribute='line')
    ip_address = fields.Field(column_name='IP地址', attribute='ip_address')

    # --- 坐标 ---
    x_coordinate = fields.Field(column_name='X坐标', attribute='x_coordinate', widget=NullableFloatWidget())
    y_coordinate = fields.Field(column_name='Y坐标', attribute='y_coordinate', widget=NullableFloatWidget())

    # --- 拓扑 ---
    direction1_neighbor_id = fields.Field(column_name='一方向邻站ID', attribute='direction1_neighbor_id', widget=NullableIntegerWidget())
    direction1_neighbor_direction = fields.Field(column_name='一方向邻站方向', attribute='direction1_neighbor_direction', widget=NullableIntegerWidget())
    direction2_neighbor_id = fields.Field(column_name='二方向邻站ID', attribute='direction2_neighbor_id', widget=NullableIntegerWidget())
    direction2_neighbor_direction = fields.Field(column_name='二方向邻站方向', attribute='direction2_neighbor_direction', widget=NullableIntegerWidget())
    direction3_neighbor_id = fields.Field(column_name='三方向邻站ID', attribute='direction3_neighbor_id', widget=NullableIntegerWidget())
    direction3_neighbor_direction = fields.Field(column_name='三方向邻站方向', attribute='direction3_neighbor_direction', widget=NullableIntegerWidget())

    # --- 使能/能力 ---
    direction1_enabled = fields.Field(column_name='一方向启用', attribute='direction1_enabled', widget=BooleanWidget())
    direction2_enabled = fields.Field(column_name='二方向启用', attribute='direction2_enabled', widget=BooleanWidget())
    direction3_enabled = fields.Field(column_name='三方向启用', attribute='direction3_enabled', widget=BooleanWidget())
    supports_auto_switch = fields.Field(column_name='具备自动切换功能', attribute='supports_auto_switch', widget=BooleanWidget())

    # ✅ 新增：电缆告警联动方式（单边/双边）
    direction1_cable_alarm_linkage = fields.Field(
        column_name='一方向电缆告警联动',
        attribute='direction1_cable_alarm_linkage',
        widget=BooleanWidget()
    )
    direction2_cable_alarm_linkage = fields.Field(
        column_name='二方向电缆告警联动',
        attribute='direction2_cable_alarm_linkage',
        widget=BooleanWidget()
    )

    # --- 地址相关 ---
    manual_address = fields.Field(column_name='人工指定地址', attribute='manual_address', widget=NullableIntegerWidget())
    is_dynamic_addressing = fields.Field(column_name='启用动态地址派发', attribute='is_dynamic_addressing', widget=BooleanWidget())
    sealed_base_addr_bcd = fields.Field(column_name='上行封连BCD首地址', attribute='sealed_base_addr_bcd', widget=NullableIntegerWidget())

    # --- 其他 ---
    remark = fields.Field(column_name='备注', attribute='remark')
    alarm_filters = fields.Field(column_name='过滤告警码', attribute='alarm_filters', widget=JSONWidget())

    class Meta:
        model = Device
        fields = (
            'device_id', 'name', 'depot', 'line', 'ip_address',
            'x_coordinate', 'y_coordinate',
            'direction1_neighbor_id', 'direction1_neighbor_direction',
            'direction2_neighbor_id', 'direction2_neighbor_direction',
            'direction3_neighbor_id', 'direction3_neighbor_direction',
            'direction1_enabled', 'direction2_enabled', 'direction3_enabled',
            'supports_auto_switch',

            # ✅ 新增导入导出字段
            'direction1_cable_alarm_linkage', 'direction2_cable_alarm_linkage',

            'manual_address', 'is_dynamic_addressing', 'sealed_base_addr_bcd',
            'remark', 'alarm_filters', 'id',   # ★ export 保留
        )
        export_order = fields

        # ★ 用资源字段名匹配已存在对象（存在就更新）
        import_id_fields = ('device_id',)

        skip_unchanged = True

    def before_import(self, dataset, **kwargs):
        if not getattr(dataset, "headers", None):
            return

        headers = [_norm_header(h) for h in dataset.headers]

        def canon(h: str) -> str:
            # 设备ID兼容
            if h in ("设备id", "设备Id", "设备ID"):
                return "设备ID"
            # 过滤告警兼容
            if h in ("过滤告警", "过滤告警码"):
                return "过滤告警码"
            # id 列兼容（有的人会写 ID / Id）
            if h in ("ID", "Id"):
                return "id"
            return h

        dataset.headers = [canon(h) for h in headers]

    def before_import_row(self, row, row_number=None, **kwargs):
        # ★ 再保险：就算有人把 id 列留着，也强制不让它参与导入
        row.pop('id', None)
        row.pop('ID', None)
        row.pop('Id', None)

        # 设备ID必填
        v = row.get('设备ID') or row.get('设备id') or row.get('设备Id')
        if v is None or (isinstance(v, str) and v.strip() == ""):
            raise ValidationError(f"第 {row_number} 行：设备ID 不能为空（必须填整数）")

        # 过滤告警默认
        if not row.get('过滤告警码'):
            if row.get('过滤告警'):
                row['过滤告警码'] = row.get('过滤告警')
            else:
                row['过滤告警码'] = '[]'

        # ✅ 新字段容错：空值默认为 False（可选，但建议）
        # import-export + BooleanWidget 有时对 "" 会报错，这里提前兜底
        for k in ('一方向电缆告警联动', '二方向电缆告警联动'):
            if k in row and (row[k] is None or (isinstance(row[k], str) and row[k].strip() == "")):
                row[k] = "False"

    # 兜底：部分版本实例匹配不稳定时，强制用 device_id 找到老对象用于更新
    def get_instance(self, instance_loader, row):
        raw = row.get('设备ID') or row.get('设备id') or row.get('设备Id')
        try:
            did = int(str(raw).strip())
        except Exception:
            return None
        try:
            return Device.objects.get(device_id=did)
        except Device.DoesNotExist:
            return None


@admin.register(Device)
class DeviceAdmin(ImportExportModelAdmin):
    resource_class = DeviceResource

    list_display = (
        'device_id', 'name', 'depot', 'line', 'ip_address',
        'x_coordinate', 'y_coordinate',
        'direction1_neighbor_id', 'direction1_neighbor_direction',
        'direction2_neighbor_id', 'direction2_neighbor_direction',
        'direction3_neighbor_id', 'direction3_neighbor_direction',
        'direction1_enabled', 'direction2_enabled', 'direction3_enabled',
        'supports_auto_switch',

        # ✅ 新增展示
        'direction1_cable_alarm_linkage', 'direction2_cable_alarm_linkage',

        'manual_address', 'is_dynamic_addressing', 'sealed_base_addr_bcd',
        'remark',
    )
    list_filter = (
        'depot', 'line',
        'direction1_enabled', 'direction2_enabled', 'direction3_enabled',
        'supports_auto_switch', 'is_dynamic_addressing',

        # ✅ 新增筛选（可选但建议）
        'direction1_cable_alarm_linkage', 'direction2_cable_alarm_linkage',
    )
    search_fields = ('device_id', 'name', 'ip_address', 'depot', 'line')
    ordering = ('device_id',)
    actions = [send_reconnect_command]


# ========================
# 文件上传
# ========================
@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'upload_time', 'file_link')
    search_fields = ('name',)
    list_filter = ('upload_time',)

    def file_link(self, obj):
        if obj.file:
            return format_html('<a href="{}" target="_blank">下载</a>', obj.file.url)
        return "-"
    file_link.short_description = '文件下载链接'
