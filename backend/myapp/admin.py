from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from .models import Device, SwitchData, AlarmActive, AnalogData, AlarmData, RelayAction, UserOperation, UploadedFile
from django_admin_filters import DateRange
from django.utils import timezone
from django.utils.html import format_html
from django.apps import AppConfig

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

        # 仅当用户对象具有有效 depot 权限列表时进行过滤
        if hasattr(user, 'depots') and isinstance(user.depots, list):
            return qs.filter(**{f"{self.depot_filter_field}__in": user.depots})

        return qs.none()




# ========================
# 公共工具函数
# ========================
def batch_confirm(modeladmin, request, queryset):# 定义批量确认函数
    updated_count = queryset.update(is_confirmed=True)
    modeladmin.message_user(request, f"成功确认 {updated_count} 条告警。")
batch_confirm.short_description = "确认选中的告警"

def batch_delete(modeladmin, request, queryset):# 定义批量删除函数
    batch_size = 1000
    queryset = queryset.iterator()
    deleted_count = 0
    while True:
        ids = []
        for _ in range(batch_size):
            try:
                ids.append(next(queryset).id)
            except StopIteration:
                break
        if not ids:
            break
        modeladmin.model.objects.filter(id__in=ids).delete()
        deleted_count += len(ids)
    print(f'成功删除 {deleted_count} 条记录')
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
# 当前告警
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
# 历史告警
# ========================
class AlarmDataResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    alarm_code = fields.Field(column_name='告警码', attribute='alarm_code')
    alarm_meaning = fields.Field(column_name='告警含义')
    timestamp_start = fields.Field(column_name='告警开始时间')
    timestamp_end = fields.Field(column_name='告警结束时间')
    confirmed_status = fields.Field(column_name='确认状态')

    class Meta:
        model = AlarmData
        fields = ('timestamp_start', 'timestamp_end', 'device__device_id', 'alarm_code', 'alarm_meaning', 'confirmed_status', 'id')
        export_order = fields

    def dehydrate_alarm_meaning(self, alarm): return alarm.alarm_meaning
    def dehydrate_device__device_id(self, alarm): return alarm.device.device_id
    def dehydrate_confirmed_status(self, obj): return "已确认" if obj.is_confirmed else "未确认"
    def dehydrate_timestamp_start(self, alarm): return timezone.localtime(alarm.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')
    def dehydrate_timestamp_end(self, alarm):
        return timezone.localtime(alarm.timestamp_end).strftime('%Y-%m-%d %H:%M:%S') if alarm.timestamp_end else ""

@admin.register(AlarmData)
class AlarmDataAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = AlarmDataResource
    list_display = ('timestamp_start_display', 'timestamp_end_display', 'device', 'alarm_code', 'alarm_meaning', 'show_confirmed_status')
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (('timestamp_start', MyDateRangePicker), 'device__name', 'device__device_id', 'alarm_code', 'is_confirmed')
    actions = [batch_delete, batch_confirm]
    def alarm_meaning(self, obj): return obj.alarm_meaning
    def show_confirmed_status(self, obj): return obj.confirmed_status_display()
    def timestamp_start_display(self, obj): return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')
    def timestamp_end_display(self, obj): return timezone.localtime(obj.timestamp_end).strftime('%Y-%m-%d %H:%M:%S') if obj.timestamp_end else ""
    show_confirmed_status.admin_order_field = 'is_confirmed'
    show_confirmed_status.short_description = '确认状态'
    timestamp_start_display.admin_order_field = 'timestamp_start'
    timestamp_end_display.admin_order_field = 'timestamp_end'

# ========================
# 开关量
# ========================
class SwitchDataResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    switch_status = fields.Field(column_name='开关量数据包')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')
    class Meta:
        model = SwitchData
        fields = ('时间', '设备', '开关量数据包', 'id')
        export_order = fields
    def dehydrate_switch_status(self, switch_data): return switch_data.get_status_bits()
    def dehydrate_timestamp(self, switch_data):
        return timezone.localtime(switch_data.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

@admin.register(SwitchData)
class SwitchDataAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = SwitchDataResource
    list_display = ('timestamp_with_seconds', 'device', 'formatted_switch_status')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id')
    search_fields = ('device__device_id', 'device__ip_address', 'device__name')
    actions = [batch_delete]
    def formatted_switch_status(self, obj): return obj.get_status_bits()
    def timestamp_with_seconds(self, obj): return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

# ========================
# 电压电流
# ========================
class AnalogDataResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')
    voltage_1 = fields.Field(column_name='电压1(V)', attribute='voltage_1')
    current_1 = fields.Field(column_name='电流1(A)', attribute='current_1')
    voltage_2 = fields.Field(column_name='电压2(V)', attribute='voltage_2')
    current_2 = fields.Field(column_name='电流2(A)', attribute='current_2')
    id = fields.Field(column_name='ID', attribute='id')
    class Meta:
        model = AnalogData
        fields = ('时间', '设备', '电压1(V)', '电流1(A)', '电压2(V)', '电流2(A)', 'id')
        export_order = fields
    def dehydrate_timestamp(self, analog_data): return timezone.localtime(analog_data.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

@admin.register(AnalogData)
class AnalogDataAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = AnalogDataResource
    list_display = ('timestamp_with_seconds', 'device', 'voltage_1', 'current_1', 'voltage_2', 'current_2')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id')
    search_fields = ('device__device_id', 'device__ip_address', 'device__name')
    actions = [batch_delete]
    def timestamp_with_seconds(self, obj): return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

# ========================
# 用户操作
# ========================
class UserOperationResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    function_code = fields.Field(column_name='操作码', attribute='function_code')
    operation = fields.Field(column_name='操作', attribute='operation')
    username = fields.Field(column_name='用户名', attribute='username')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')
    class Meta:
        model = UserOperation
        fields = ('时间', '设备', '操作码', '操作', '用户名', 'id')
        export_order = fields
    def dehydrate_timestamp(self, obj): return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S')
    def dehydrate_username(self, obj): return obj.username

@admin.register(UserOperation)
class UserOperationAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = UserOperationResource
    list_display = ('timestamp_with_seconds', 'device', 'operation', 'username')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'operation', 'username')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'operation', 'username')
    actions = [batch_delete]
    def timestamp_with_seconds(self, obj): return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S')

# ========================
# 继电器动作
# ========================
class RelayActionResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    relay = fields.Field(column_name='继电器', attribute='relay')
    action = fields.Field(column_name='动作', attribute='action')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')
    class Meta:
        model = RelayAction
        fields = ('时间', '设备', '继电器', '动作', 'id')
        export_order = fields
    def dehydrate_timestamp(self, obj): return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

@admin.register(RelayAction)
class RelayActionAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = RelayActionResource
    list_display = ('timestamp_with_seconds', 'device', 'relay', 'action')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'relay', 'action')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'relay', 'action')
    actions = [batch_delete]
    def timestamp_with_seconds(self, obj): return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

# ========================
# 设备
# ========================
class DeviceResource(resources.ModelResource):
    class Meta:
        model = Device
        fields = (
            'device_id', 'name', 'line', 'ip_address', 'x_coordinate', 'y_coordinate',
            'direction1_neighbor_id', 'direction1_neighbor_direction',
            'direction2_neighbor_id', 'direction2_neighbor_direction',
            'remark', 'alarm_filters', 'id'
        )
        export_order = fields

@admin.register(Device)
class DeviceAdmin(DepotScopedAdmin, ImportExportModelAdmin):
    resource_class = DeviceResource
    list_display = ('device_id', 'name', 'depot', 'line', 'ip_address', 'x_coordinate', 'y_coordinate',
                    'direction1_neighbor_id', 'direction1_neighbor_direction',
                    'direction2_neighbor_id', 'direction2_neighbor_direction')
    search_fields = ('device_id', 'name', 'depot', 'line', 'ip_address')

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

# ========================
# 用户
# ========================
CustomUser = get_user_model()

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'is_staff', 'is_active', 'depots')
    search_fields = ('username', 'email')
    ordering = ('username',)
    fieldsets = UserAdmin.fieldsets + (('车间管理', {'fields': ('depots',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('车间管理', {'fields': ('depots',)}),)
    def get_model_perms(self, request): return super().get_model_perms(request)
    class Media:
        css = {'all': ('admin/css/widgets.css',)}


