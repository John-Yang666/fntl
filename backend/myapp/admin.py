# admin.py
import os
import logging
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import time

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import format_html

from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import JSONWidget, BooleanWidget, ManyToManyWidget

from django_admin_filters import DateRange

from .models import (
    Device, SwitchData, AlarmActive, AnalogData, AlarmData,
    RelayAction, UserOperation, UploadedFile
)

logger = logging.getLogger(__name__)

# ========================
# ✅ 导出安全基类：屏蔽 stdout/stderr，避免任何输出污染 xlsx 二进制流
# ========================
class SafeImportExportModelAdmin(ImportExportModelAdmin):
    """
    有些部署组合下（容器日志、调试捕获、错误输出等），stdout/stderr 可能污染导出响应体，
    导致“文件名正确但内容变成日志/乱码”。此处强制屏蔽导出动作期间的输出。
    """
    def export_action(self, request, *args, **kwargs):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return super().export_action(request, *args, **kwargs)


# ========================
# 通用权限过滤基类
# ========================
class DepotScopedAdmin(admin.ModelAdmin):
    """
    通用 Admin 权限控制：根据 user.depots 限制数据范围。
    可通过 depot_filter_field 配置字段路径（支持 device__depot）。
    """
    depot_filter_field = 'depot'  # 子类可设置为 'device__depot' 等

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user

        if user.is_superuser:
            return qs

        if hasattr(user, 'depots') and isinstance(user.depots, list):
            return qs.filter(**{f"{self.depot_filter_field}__in": user.depots})

        return qs.none()


# ========================
# 公共工具函数（批量动作）
# ========================
def batch_confirm(modeladmin, request, queryset):
    """批量确认告警"""
    updated_count = queryset.update(is_confirmed=True)
    modeladmin.message_user(request, f"成功确认 {updated_count} 条告警。")
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

    # ✅ 不用 print，避免输出污染导出/响应；用 logger
    logger.info("batch_delete: deleted=%s model=%s", deleted_count, modeladmin.model.__name__)
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
# 当前告警（不需要导出）
# ========================
@admin.register(AlarmActive)
class AlarmActiveAdmin(DepotScopedAdmin):
    depot_filter_field = 'device__depot'
    list_display = ('timestamp_start_display', 'device', 'alarm_code', 'alarm_meaning', 'show_confirmed_status')
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (('timestamp_start', MyDateRangePicker), 'device__name', 'device__device_id', 'alarm_code', 'is_confirmed')
    actions = [batch_delete, batch_confirm]

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
# 历史告警（导入导出）
# ========================
class AlarmDataResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备ID', attribute='device')
    alarm_code = fields.Field(column_name='告警码', attribute='alarm_code')
    alarm_meaning = fields.Field(column_name='告警含义')
    timestamp_start = fields.Field(column_name='告警开始时间', attribute='timestamp_start')
    timestamp_end = fields.Field(column_name='告警结束时间', attribute='timestamp_end')
    confirmed_status = fields.Field(column_name='确认状态')

    class Meta:
        model = AlarmData
        # ✅ Meta.fields 必须是“字段名”，不是 column_name 的中文
        fields = ('timestamp_start', 'timestamp_end', 'device__device_id', 'alarm_code', 'alarm_meaning', 'confirmed_status', 'id')
        export_order = ('timestamp_start', 'timestamp_end', 'device__device_id', 'alarm_code', 'alarm_meaning', 'confirmed_status', 'id')

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_alarm_meaning(self, obj):
        return obj.alarm_meaning

    def dehydrate_confirmed_status(self, obj):
        return obj.confirmed_status_display()

    def dehydrate_timestamp_start(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')

    def dehydrate_timestamp_end(self, obj):
        return timezone.localtime(obj.timestamp_end).strftime('%Y-%m-%d %H:%M:%S') if obj.timestamp_end else ""


@admin.register(AlarmData)
class AlarmDataAdmin(DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = AlarmDataResource
    list_display = ('timestamp_start_display', 'timestamp_end_display', 'device', 'alarm_code', 'alarm_meaning', 'show_confirmed_status')
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (('timestamp_start', MyDateRangePicker), 'device__name', 'device__device_id', 'alarm_code', 'is_confirmed')
    actions = [batch_delete, batch_confirm]

    def alarm_meaning(self, obj):
        return obj.alarm_meaning

    def show_confirmed_status(self, obj):
        return obj.confirmed_status_display()

    def timestamp_start_display(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')

    def timestamp_end_display(self, obj):
        return timezone.localtime(obj.timestamp_end).strftime('%Y-%m-%d %H:%M:%S') if obj.timestamp_end else ""

    alarm_meaning.short_description = '告警含义'
    show_confirmed_status.admin_order_field = 'is_confirmed'
    show_confirmed_status.short_description = '确认状态'
    timestamp_start_display.admin_order_field = 'timestamp_start'
    timestamp_start_display.short_description = '开始时间'
    timestamp_end_display.admin_order_field = 'timestamp_end'
    timestamp_end_display.short_description = '结束时间'


# ========================
# 开关量（导入导出）
# ========================
class SwitchDataResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备ID', attribute='device')
    switch_status = fields.Field(column_name='开关量数据包')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')

    class Meta:
        model = SwitchData
        fields = ('timestamp', 'device__device_id', 'switch_status', 'id')
        export_order = ('timestamp', 'device__device_id', 'switch_status', 'id')

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_switch_status(self, obj):
        # ✅ 转成可读字符串，避免 bytes/对象直出
        return obj.get_status_bits()

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')


@admin.register(SwitchData)
class SwitchDataAdmin(DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = SwitchDataResource
    list_display = ('timestamp_with_seconds', 'device', 'formatted_switch_status')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id')
    search_fields = ('device__device_id', 'device__ip_address', 'device__name')
    actions = [batch_delete]

    def formatted_switch_status(self, obj):
        return obj.get_status_bits()

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

    formatted_switch_status.short_description = '开关量数据包'
    timestamp_with_seconds.short_description = '时间'


# ========================
# 电压电流（导入导出）
# ========================
class AnalogDataResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备ID', attribute='device')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')
    voltage_1 = fields.Field(column_name='电压1(V)', attribute='voltage_1')
    current_1 = fields.Field(column_name='电流1(mA)', attribute='current_1')
    voltage_2 = fields.Field(column_name='电压2(V)', attribute='voltage_2')
    current_2 = fields.Field(column_name='电流2(mA)', attribute='current_2')

    class Meta:
        model = AnalogData
        fields = ('timestamp', 'device__device_id', 'voltage_1', 'current_1', 'voltage_2', 'current_2', 'id')
        export_order = ('timestamp', 'device__device_id', 'voltage_1', 'current_1', 'voltage_2', 'current_2', 'id')

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')


@admin.register(AnalogData)
class AnalogDataAdmin(DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = AnalogDataResource
    list_display = ('timestamp_with_seconds', 'device', 'voltage_1', 'current_1', 'voltage_2', 'current_2')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id')
    search_fields = ('device__device_id', 'device__ip_address', 'device__name')
    actions = [batch_delete]

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')


# ========================
# 用户（导入导出）
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
class CustomUserAdmin(UserAdmin, SafeImportExportModelAdmin):
    resource_class = CustomUserResource
    list_display = ('username', 'email', 'is_staff', 'is_active', 'depots')
    search_fields = ('username', 'email')
    ordering = ('username',)
    fieldsets = UserAdmin.fieldsets + (('车间管理', {'fields': ('depots',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('车间管理', {'fields': ('depots',)}),)

    class Media:
        css = {'all': ('admin/css/widgets.css',)}


# ========================
# 用户操作（导入导出）
# ========================
class UserOperationResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备ID', attribute='device')
    function_code = fields.Field(column_name='操作码', attribute='function_code')
    operation = fields.Field(column_name='操作', attribute='operation')
    username = fields.Field(column_name='用户名', attribute='username')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')

    class Meta:
        model = UserOperation
        fields = ('timestamp', 'device__device_id', 'function_code', 'operation', 'username', 'id')
        export_order = ('timestamp', 'device__device_id', 'function_code', 'operation', 'username', 'id')

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S')

    def dehydrate_username(self, obj):
        return obj.username


@admin.register(UserOperation)
class UserOperationAdmin(DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = UserOperationResource
    list_display = ('timestamp_with_seconds', 'device', 'operation', 'username')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'operation', 'username')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'operation', 'username')
    actions = [batch_delete]

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S')


# ========================
# 继电器动作（导入导出）
# ========================
class RelayActionResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备ID', attribute='device')
    relay = fields.Field(column_name='继电器', attribute='relay')
    action = fields.Field(column_name='动作', attribute='action')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')

    class Meta:
        model = RelayAction
        fields = ('timestamp', 'device__device_id', 'relay', 'action', 'id')
        export_order = ('timestamp', 'device__device_id', 'relay', 'action', 'id')

    def dehydrate_device__device_id(self, obj):
        return obj.device.device_id if obj.device else ""

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

    def dehydrate_relay(self, obj):
        # ✅ 确保导出为字符串（避免 bytes/枚举对象）
        return str(obj.relay) if obj.relay is not None else ""

    def dehydrate_action(self, obj):
        return str(obj.action) if obj.action is not None else ""


@admin.register(RelayAction)
class RelayActionAdmin(DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = RelayActionResource
    list_display = ('timestamp_with_seconds', 'device', 'relay', 'action')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'relay', 'action')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'relay', 'action')
    actions = [batch_delete]

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')


# ========================
# 设备（导入导出 & 重连动作）
# ========================
class DeviceResource(resources.ModelResource):
    device_id = fields.Field(column_name='设备id', attribute='device_id')
    name = fields.Field(column_name='设备名称', attribute='name')
    depot = fields.Field(column_name='车间', attribute='depot')
    line = fields.Field(column_name='线路', attribute='line')
    ip_address = fields.Field(column_name='IP地址', attribute='ip_address')
    x_coordinate = fields.Field(column_name='X坐标', attribute='x_coordinate')
    y_coordinate = fields.Field(column_name='Y坐标', attribute='y_coordinate')

    direction1_neighbor_id = fields.Field(column_name='一方向邻站ID', attribute='direction1_neighbor_id')
    direction1_neighbor_direction = fields.Field(column_name='一方向邻站方向', attribute='direction1_neighbor_direction')
    direction2_neighbor_id = fields.Field(column_name='二方向邻站ID', attribute='direction2_neighbor_id')
    direction2_neighbor_direction = fields.Field(column_name='二方向邻站方向', attribute='direction2_neighbor_direction')

    direction1_enabled = fields.Field(column_name='一方向启用', attribute='direction1_enabled', widget=BooleanWidget())
    direction2_enabled = fields.Field(column_name='二方向启用', attribute='direction2_enabled', widget=BooleanWidget())

    remark = fields.Field(column_name='备注', attribute='remark')
    # 如果 alarm_filters 是 JSON/数组，建议用 JSONWidget；如果是 CharField 保持原样也行
    alarm_filters = fields.Field(column_name='过滤告警码', attribute='alarm_filters')

    class Meta:
        model = Device
        fields = (
            'device_id', 'name', 'depot', 'line', 'ip_address',
            'x_coordinate', 'y_coordinate',
            'direction1_neighbor_id', 'direction1_neighbor_direction',
            'direction2_neighbor_id', 'direction2_neighbor_direction',
            'direction1_enabled', 'direction2_enabled',
            'remark', 'alarm_filters', 'id',
        )
        export_order = fields


# ===== 重连动作所需：Redis Streams 发送（仅保留 redis_stream） =====
try:
    import redis as redis_lib
except Exception:
    redis_lib = None

REDIS_STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis_stream")
REDIS_STREAM_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_CMD_STREAM_KEY = os.getenv("REDIS_CMD_STREAM_KEY", "stream:udp:cmd")
REDIS_STREAM_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", "200000"))

_redis_cmd = None
def _get_redis_cmd():
    global _redis_cmd
    if _redis_cmd is None:
        if redis_lib is None:
            raise RuntimeError("redis-py 不可用，请 pip install redis")
        _redis_cmd = redis_lib.Redis(host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT, decode_responses=False)
    return _redis_cmd

def _send_cmd_via_redis_stream(*, target_ip: str, packet: bytes) -> None:
    r = _get_redis_cmd()
    ts_ms = int(time.time() * 1000)
    fields = {
        b"type": b"cmd",
        b"src": b"admin_reconnect",
        b"ts": str(ts_ms).encode(),
        b"ip": target_ip.encode(),
        b"payload": packet,
    }
    r.xadd(
        name=REDIS_CMD_STREAM_KEY,
        fields=fields,
        maxlen=REDIS_STREAM_MAXLEN,
        approximate=True,
    )

def _build_reconnect_packet_fixed_addr() -> bytes:
    """
    固定“重连命令”数据包：
    7F 7F 01 0B 00 00 00 00 00 00 00 00 0C 00 F7 F7
    """
    return bytes.fromhex("7F 7F 01 0B 00 00 00 00 00 00 00 00 0C 00 F7 F7")


@admin.action(description="对所选设备发送【重连】命令")
def send_reconnect_command(modeladmin, request, queryset):
    ok, fail = 0, 0
    missing_ip = []

    pkt = _build_reconnect_packet_fixed_addr()

    for dev in queryset:
        target_ip = getattr(dev, "ip_address", None)
        if not target_ip:
            missing_ip.append(str(getattr(dev, "device_id", dev.pk)))
            continue

        try:
            _send_cmd_via_redis_stream(target_ip=target_ip, packet=pkt)
            ok += 1

            UserOperation.objects.create(
                device=dev,
                function_code=0x0B,
                operation=f"发送重连命令到 {target_ip}（backend=redis_stream）",
                username=request.user.username,
                timestamp=timezone.now()
            )

        except Exception:
            fail += 1
            logger.exception(
                "[ADMIN reconnect] device=%s ip=%s send failed",
                getattr(dev, "device_id", dev.pk),
                target_ip,
            )

    if ok:
        messages.success(request, f"已向 {ok} 台设备发送【重连】命令（redis_stream），并记录操作日志。")
    if fail:
        messages.error(request, f"{fail} 台设备发送失败，详见服务器日志。")
    if missing_ip:
        messages.warning(request, f"以下设备未配置 IP，已跳过：{', '.join(missing_ip)}")


@admin.register(Device)
class DeviceAdmin(DepotScopedAdmin, SafeImportExportModelAdmin):
    resource_class = DeviceResource
    list_display = (
        'device_id', 'name', 'depot', 'line', 'ip_address',
        'x_coordinate', 'y_coordinate',
        'direction1_neighbor_id', 'direction1_neighbor_direction',
        'direction2_neighbor_id', 'direction2_neighbor_direction',
        'direction1_enabled', 'direction2_enabled',
    )
    search_fields = ('device_id', 'name', 'depot', 'line', 'ip_address')
    list_filter = ('depot', 'line', 'direction1_enabled', 'direction2_enabled')
    actions = [send_reconnect_command]


# ========================
# 文件上传（不限制权限）
# ========================
@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'upload_time', 'file_link')
    search_fields = ('name', )
    list_filter = ('upload_time',)

    def file_link(self, obj):
        if obj.file:
            return format_html('<a href="{}" target="_blank">下载</a>', obj.file.url)
        return "-"
    file_link.short_description = '文件下载链接'