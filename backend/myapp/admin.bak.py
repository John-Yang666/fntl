#20250610

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
#from import_export.formats.base_formats import XLSX
from .models import Device, SwitchData, AlarmActive, AnalogData, AlarmData, RelayAction, UserOperation, UploadedFile
from django_admin_filters import DateRange
from django.utils import timezone
from django.utils.html import format_html

# 定义批量确认函数
def batch_confirm(modeladmin, request, queryset):
    """
    将选中的告警记录统一标记为“已确认”。
    """
    updated_count = queryset.update(is_confirmed=True)
    modeladmin.message_user(request, f"成功确认 {updated_count} 条告警。")

batch_confirm.short_description = "确认选中的告警"

# 定义批量删除函数
def batch_delete(modeladmin, request, queryset):
    batch_size = 1000
    total = queryset.count()

    # 使用 iterator() 来遍历 queryset
    queryset = queryset.iterator()

    # 统计已删除的记录数
    deleted_count = 0

    while True:
        # 获取当前批次的 ids
        ids = []
        for i in range(batch_size):
            try:
                # 获取下一条数据的 id
                ids.append(next(queryset).id)
            except StopIteration:
                break  # 如果没有更多数据了，停止

        if not ids:
            break  # 如果 ids 为空，说明所有记录已经删除

        # 批量删除
        modeladmin.model.objects.filter(id__in=ids).delete()

        # 记录删除数量
        deleted_count += len(ids)

    # 输出日志或提示删除完成
    print(f'成功删除 {deleted_count} 条记录')

batch_delete.short_description = '强制删除选中的项目'


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

#当前告警
@admin.register(AlarmActive)
class AlarmActiveAdmin(admin.ModelAdmin):
    list_display = (
        'timestamp_start_display',
        'device', 'alarm_code', 'alarm_meaning', 'show_confirmed_status'
    )
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (
        ('timestamp_start', MyDateRangePicker),
        'device__name', 'device__device_id', 'alarm_code', 'is_confirmed'
    )
    actions = [batch_delete, batch_confirm]

    def alarm_meaning(self, obj):
        return obj.alarm_meaning
    alarm_meaning.short_description = '告警含义'

    def show_confirmed_status(self, obj):
        return obj.confirmed_status_display()
    show_confirmed_status.admin_order_field = 'is_confirmed'
    show_confirmed_status.short_description = '确认状态'

    def timestamp_start_display(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')
    timestamp_start_display.admin_order_field = 'timestamp_start'
    timestamp_start_display.short_description = '开始时间'


#历史告警
class AlarmDataResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    alarm_code = fields.Field(column_name='告警码', attribute='alarm_code')
    alarm_meaning = fields.Field(column_name='告警含义')
    timestamp_start = fields.Field(column_name='告警开始时间')
    timestamp_end = fields.Field(column_name='告警结束时间')
    confirmed_status = fields.Field(column_name='确认状态')

    class Meta:
        model = AlarmData
        fields = (
            'timestamp_start',
            'timestamp_end',
            'device__device_id',
            'alarm_code',
            'alarm_meaning',
            'confirmed_status',
            'id',
        )
        export_order = (
            'timestamp_start',
            'timestamp_end',
            'device__device_id',
            'alarm_code',
            'alarm_meaning',
            'confirmed_status',
            'id',
        )

    def dehydrate_alarm_meaning(self, alarm):
        return alarm.alarm_meaning

    def dehydrate_device__device_id(self, alarm):
        return alarm.device.device_id

    def dehydrate_confirmed_status(self, obj):
        return "已确认" if obj.is_confirmed else "未确认"

    def dehydrate_timestamp_start(self, alarm):
        return timezone.localtime(alarm.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')

    def dehydrate_timestamp_end(self, alarm):
        if alarm.timestamp_end:
            return timezone.localtime(alarm.timestamp_end).strftime('%Y-%m-%d %H:%M:%S')
        return ""

@admin.register(AlarmData)
class AlarmDataAdmin(ImportExportModelAdmin):
    resource_class = AlarmDataResource
    list_display = (
        'timestamp_start_display', 'timestamp_end_display',
        'device', 'alarm_code', 'alarm_meaning', 'show_confirmed_status'
    )
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (
        ('timestamp_start', MyDateRangePicker),
        'device__name', 'device__device_id', 'alarm_code', 'is_confirmed'
    )
    actions = [batch_delete, batch_confirm]

    def alarm_meaning(self, obj):
        return obj.alarm_meaning
    alarm_meaning.short_description = '告警含义'

    def show_confirmed_status(self, obj):
        return obj.confirmed_status_display()
    show_confirmed_status.admin_order_field = 'is_confirmed'
    show_confirmed_status.short_description = '确认状态'

    def timestamp_start_display(self, obj):
        return timezone.localtime(obj.timestamp_start).strftime('%Y-%m-%d %H:%M:%S')
    timestamp_start_display.admin_order_field = 'timestamp_start'
    timestamp_start_display.short_description = '开始时间'

    def timestamp_end_display(self, obj):
        if obj.timestamp_end:
            return timezone.localtime(obj.timestamp_end).strftime('%Y-%m-%d %H:%M:%S')
        return ""
    timestamp_end_display.admin_order_field = 'timestamp_end'
    timestamp_end_display.short_description = '结束时间'


#开关量数据
class SwitchDataResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    switch_status = fields.Field(column_name='开关量数据包')  # 假设 SwitchData 模型有这个字段
    timestamp = fields.Field(column_name='时间', attribute='timestamp')

    class Meta:
        model = SwitchData
        fields = ('时间', '设备', '开关量数据包', 'id')
        export_order = ('时间', '设备', '开关量数据包', 'id')

    def dehydrate_device_name(self, switch_data):
        return switch_data.device.name  # 获取设备名称
    
    def dehydrate_switch_status(self, switch_data):
        return switch_data.get_status_bits()  # 获取开关状态

    def dehydrate_timestamp(self, switch_data):
        local_timestamp = timezone.localtime(switch_data.timestamp)
        return local_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')  # 格式化时间

@admin.register(SwitchData)
class SwitchDataAdmin(ImportExportModelAdmin):
    resource_class = SwitchDataResource  # 绑定到资源类
    list_display = ('timestamp_with_seconds', 'device', 'formatted_switch_status')

    # 添加自定义过滤器
    list_filter = (('timestamp', MyDateRangePicker),'device__name', 'device__device_id')

    search_fields = ('device__device_id', 'device__ip_address', 'device__name')

    # 注册自定义操作
    actions = [batch_delete]



    def formatted_switch_status(self, obj):
        return obj.get_status_bits()  # 假设这个方法能返回开关状态

    def timestamp_with_seconds(self, obj):
        local_timestamp = timezone.localtime(obj.timestamp)
        return local_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp_with_seconds.admin_order_field = 'timestamp'
    timestamp_with_seconds.short_description = '时间'


#用户操作
class UserOperationResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    function_code = fields.Field(column_name='操作码', attribute='function_code')
    operation = fields.Field(column_name='操作', attribute='operation')
    username = fields.Field(column_name='用户名', attribute='username')  # 添加用户名字段
    timestamp = fields.Field(column_name='时间', attribute='timestamp')

    class Meta:
        model = UserOperation
        fields = ('时间', '设备', '操作码', '操作', '用户名', 'id')
        export_order = ('时间', '设备', '操作码', '操作', '用户名', 'id')

    def dehydrate_device_name(self, user_operation):
        return user_operation.device.name

    def dehydrate_timestamp(self, user_operation):
        local_timestamp = timezone.localtime(user_operation.timestamp)
        return local_timestamp.strftime('%Y-%m-%d %H:%M:%S')

    def dehydrate_username(self, user_operation):
        return user_operation.username  # 确保导出时显示用户名


@admin.register(UserOperation)
class UserOperationAdmin(ImportExportModelAdmin):
    resource_class = UserOperationResource
    # formats = [XLSX]  # 指定导出格式为 Excel
    list_display = ('timestamp_with_seconds', 'device', 'operation', 'username')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'operation', 'username')  # 添加用户名到搜索字段
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'operation', 'username')  # 添加用户名到筛选字段

    # 注册自定义操作
    actions = [batch_delete]

    def timestamp_with_seconds(self, obj):
        local_timestamp = timezone.localtime(obj.timestamp)
        return local_timestamp.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_with_seconds.admin_order_field = 'timestamp'
    timestamp_with_seconds.short_description = '时间'
    
#电压电流数据
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
        export_order = ('时间', '设备', '电压1(V)', '电流1(A)', '电压2(V)', '电流2(A)', 'id')

    def dehydrate_timestamp(self, analog_data):
        local_timestamp = timezone.localtime(analog_data.timestamp)
        return local_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')  # 保持微秒级时间格式

@admin.register(AnalogData)
class AnalogDataAdmin(ImportExportModelAdmin):  # 继承 ImportExportModelAdmin
    resource_class = AnalogDataResource
    list_display = ('timestamp_with_seconds', 'device', 'voltage_1', 'current_1', 'voltage_2', 'current_2')
    #search_fields = ('device__device_id', 'device__ip_address')
    actions = [batch_delete]

    # 添加自定义过滤器
    list_filter = (('timestamp', MyDateRangePicker),'device__name', 'device__device_id')
    search_fields = ('device__device_id', 'device__ip_address', 'device__name')


    def timestamp_with_seconds(self, obj):
        local_timestamp = timezone.localtime(obj.timestamp)
        return local_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp_with_seconds.admin_order_field = 'timestamp'
    timestamp_with_seconds.short_description = '时间'


#继电器动作
class RelayActionResource(resources.ModelResource):
    device__device_id = fields.Field(column_name='设备', attribute='device')
    relay = fields.Field(column_name='继电器', attribute='relay')
    action = fields.Field(column_name='动作', attribute='action')
    timestamp = fields.Field(column_name='时间', attribute='timestamp')

    class Meta:
        model = RelayAction
        fields = ('时间', '设备', '继电器', '动作', 'id')
        export_order = ('时间', '设备', '继电器', '动作', 'id')

    def dehydrate_relay(self, relay_action):
        return relay_action.relay

    def dehydrate_action(self, relay_action):
        return relay_action.action

    def dehydrate_device_name(self, relay_action):
        return relay_action.device.name

    def dehydrate_timestamp(self, relay_action):
        local_timestamp = timezone.localtime(relay_action.timestamp)
        return local_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')

@admin.register(RelayAction)
class RelayActionAdmin(ImportExportModelAdmin):
    resource_class = RelayActionResource
    #formats = [XLSX]  # 指定导出格式为 Excel
    list_display = ('timestamp_with_seconds', 'device', 'relay', 'action')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'relay', 'action', 'timestamp')
    list_filter = (('timestamp', MyDateRangePicker), 'device__name', 'device__device_id', 'relay', 'action')

    # 注册自定义操作
    actions = [batch_delete]

    def relay(self, obj):
        return obj.relay
    relay.short_description = '继电器'

    def action(self, obj):
        return obj.action
    action.short_description = '动作'

    def device_name(self, obj):
        return obj.device.name
    device_name.short_description = '设备名称'

    def timestamp_with_seconds(self, obj):
        local_timestamp = timezone.localtime(obj.timestamp)
        return local_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp_with_seconds.admin_order_field = 'timestamp'
    timestamp_with_seconds.short_description = '时间'


#设备
class DeviceResource(resources.ModelResource): #导出功能用
    device_id = fields.Field(column_name='设备id', attribute='device_id')
    name = fields.Field(column_name='设备名称', attribute='name')
    line = fields.Field(column_name='线路', attribute='line')
    ip_address = fields.Field(column_name='IP地址', attribute='ip_address')
    x_coordinate = fields.Field(column_name='X坐标', attribute='x_coordinate')
    y_coordinate = fields.Field(column_name='Y坐标', attribute='y_coordinate')
    direction1_neighbor_id = fields.Field(column_name='一方向邻站ID', attribute='direction1_neighbor_id')
    direction1_neighbor_direction = fields.Field(column_name='一方向邻站方向', attribute='direction1_neighbor_direction')
    direction2_neighbor_id = fields.Field(column_name='二方向邻站ID', attribute='direction2_neighbor_id')
    direction2_neighbor_direction = fields.Field(column_name='二方向邻站方向', attribute='direction2_neighbor_direction')
    remark = fields.Field(column_name='备注', attribute='remark')
    alarm_filters = fields.Field(column_name='过滤告警码', attribute='alarm_filters')

    class Meta:
        model = Device
        fields = ('device_id', 'name', 'line', 'ip_address', 'x_coordinate', 'y_coordinate', 
                  'direction1_neighbor_id', 'direction1_neighbor_direction', 'direction2_neighbor_id', 
                  'direction2_neighbor_direction', 'remark', 'alarm_filters', 'id')
        export_order = ('device_id', 'name', 'line', 'ip_address', 'x_coordinate', 'y_coordinate', 
                  'direction1_neighbor_id', 'direction1_neighbor_direction', 'direction2_neighbor_id', 
                  'direction2_neighbor_direction', 'remark', 'alarm_filters', 'id')
        
    def dehydrate_remark(self, device):
        return device.remark  # 在导出时获取备注内容

@admin.register(Device)
class DeviceAdmin(ImportExportModelAdmin):
    resource_class = DeviceResource
    #formats = [XLSX]  # 指定导出格式为 Excel
    list_display = ('device_id', 'name', 'depot', 'line', 'ip_address', 'x_coordinate', 'y_coordinate', 'direction1_neighbor_id',
                     'direction1_neighbor_direction', 'direction2_neighbor_id', 'direction2_neighbor_direction')
    search_fields = ('device_id', 'name', 'depot', 'line', 'ip_address')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        return qs.filter(depot__in=user.depots)

# 上传文件功能
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

CustomUser = get_user_model()

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    # 可选：显示哪些字段
    list_display = ('username', 'email', 'is_staff', 'is_active', 'depots')
    search_fields = ('username', 'email')
    ordering = ('username',)

    # 可选：在编辑页中显示哪些字段组
    fieldsets = UserAdmin.fieldsets + (
        ('车间管理', {'fields': ('depots',)}),
    )

    # 可选：在创建新用户时包含 depots 字段
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('车间管理', {'fields': ('depots',)}),
    )

    def get_model_perms(self, request):
        return super().get_model_perms(request)

    class Media:
        # 防止 admin 样式缺失（有时出现在定制用户时）
        css = {
            'all': ('admin/css/widgets.css',),
        }

CustomUser._meta.app_label = 'auth'