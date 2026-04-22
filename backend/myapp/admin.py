# admin.py
import os
import logging
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
from io import StringIO
import time

from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import connections
from django.db.models import F
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.utils.html import format_html
from django.utils.functional import cached_property

from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.forms import ExportForm
from import_export.widgets import BooleanWidget, ManyToManyWidget, ForeignKeyWidget

from .models import (
    Depot, Line, Device, SwitchData, AlarmActive, AnalogData, AlarmData,
    RelayAction, UserOperation, UploadedFile, HelpFaqEntry
)
from .udp_sender import create_packet

logger = logging.getLogger(__name__)


def _estimated_admin_count(queryset):
    if not hasattr(queryset, "query"):
        return None

    connection = connections[queryset.db]
    if connection.vendor != "postgresql":
        return None

    try:
        sql, params = queryset.query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}", params)
            row = cursor.fetchone()
    except Exception:
        logger.exception("admin count estimate failed")
        return None

    if not row:
        return None

    plan = row[0]
    if isinstance(plan, list) and plan:
        plan = plan[0]

    try:
        return max(int(plan["Plan"]["Plan Rows"]), 0)
    except (KeyError, TypeError, ValueError):
        return None


class EstimatedCountPaginator(Paginator):
    @cached_property
    def count(self):
        estimated = _estimated_admin_count(self.object_list)
        if estimated is not None:
            return estimated
        return super().count


class LargeTableAdminMixin:
    paginator = Paginator
    show_full_result_count = True
    list_per_page = 50
    list_max_show_all = 200
    list_select_related = ("device",)


class NoAddPermissionAdminMixin:
    def has_add_permission(self, request):
        return False


class ReadOnlyImportExportAdminMixin(NoAddPermissionAdminMixin):
    def has_import_permission(self, request, *args, **kwargs):
        return False


class ReadOnlyForNonSuperuserAdminMixin:
    def has_add_permission(self, request):
        if not request.user.is_superuser:
            return False
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        if not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj=obj)

    def has_import_permission(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            return False
        parent = getattr(super(), "has_import_permission", None)
        if parent is None:
            return False
        return parent(request, *args, **kwargs)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            return {}
        return actions

# ========================
# ✅ 导出安全基类：屏蔽 stdout/stderr，避免任何输出污染 xlsx 二进制流
# ========================
class SafeImportExportModelAdmin(ReadOnlyForNonSuperuserAdminMixin, ImportExportModelAdmin):
    """
    有些部署组合下（容器日志、调试捕获、错误输出等），stdout/stderr 可能污染导出响应体，
    导致“文件名正确但内容变成日志/乱码”。此处强制屏蔽导出动作期间的输出。
    同时统一使用非 Selectable 导出表单，避免自定义字段在 export_fields 过滤阶段被丢弃。
    """
    export_form_class = ExportForm

    def export_action(self, request, *args, **kwargs):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return super().export_action(request, *args, **kwargs)


# ========================
# 通用权限过滤基类
# ========================
class DepotScopedAdmin(ReadOnlyForNonSuperuserAdminMixin, admin.ModelAdmin):
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

        if hasattr(user, "managed_depots_qs"):
            depots_qs = user.managed_depots_qs()
            if depots_qs.exists():
                return qs.filter(**{f"{self.depot_filter_field}__in": depots_qs})

        return qs.none()

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("truncate_table", None)
        return actions

    def changelist_view(self, request, extra_context=None):
        # Django admin 默认要求 action 必须勾选条目；为“清空整表”放宽该限制。
        if request.method == "POST" and request.POST.get("action") == "truncate_table":
            selected = request.POST.getlist(ACTION_CHECKBOX_NAME)
            select_across = request.POST.get("select_across") == "1"
            if not selected and not select_across:
                actions = self.get_actions(request)
                action = actions.get("truncate_table")
                if action:
                    queryset = self.get_queryset(request).none()
                    response = action[0](self, request, queryset)
                    if response is not None:
                        return response
                    return HttpResponseRedirect(request.get_full_path())
        return super().changelist_view(request, extra_context=extra_context)


class StrictNameManyToManyWidget(ManyToManyWidget):
    def clean(self, value, row=None, **kwargs):
        if value in (None, ""):
            return self.model.objects.none()

        names = [item.strip() for item in str(value).split(self.separator) if item.strip()]
        if not names:
            return self.model.objects.none()

        queryset = self.model.objects.filter(**{f"{self.field}__in": names})
        found_names = set(queryset.values_list(self.field, flat=True))
        missing_names = [name for name in names if name not in found_names]
        if missing_names:
            raise ValidationError(f"以下名称不存在，请先在后台配置：{', '.join(missing_names)}")
        return queryset


@admin.register(Depot)
class DepotAdmin(ReadOnlyForNonSuperuserAdminMixin, admin.ModelAdmin):
    list_display = ("name", "is_active", "ordering", "remark")
    search_fields = ("name", "remark")
    list_filter = ("is_active",)
    ordering = ("ordering", "name")


@admin.register(Line)
class LineAdmin(ReadOnlyForNonSuperuserAdminMixin, admin.ModelAdmin):
    list_display = ("name", "is_active", "ordering", "remark")
    search_fields = ("name", "remark")
    list_filter = ("is_active",)
    ordering = ("ordering", "name")


@admin.register(HelpFaqEntry)
class HelpFaqEntryAdmin(ReadOnlyForNonSuperuserAdminMixin, admin.ModelAdmin):
    list_display = ("display_order", "title", "updated_at")
    ordering = ("display_order", "id")


# ========================
# 公共工具函数（批量动作）
# ========================
def batch_confirm(modeladmin, request, queryset):
    """批量确认告警"""
    updated_count = queryset.update(is_confirmed=True)
    modeladmin.message_user(request, f"成功确认 {updated_count} 条告警。")
batch_confirm.short_description = "确认选中的告警"


def batch_delete(modeladmin, request, queryset):
    """批量强制删除（高性能分批版）"""
    batch_size = max(int(os.getenv("ADMIN_BATCH_DELETE_SIZE", "20000")), 1000)
    model = modeladmin.model
    pk_name = model._meta.pk.name
    using = queryset.db
    deleted_count = 0

    # 删除场景不需要排序；清空 ORDER BY 可避免千万级数据的大排序开销。
    base_queryset = queryset.order_by()

    while True:
        pk_subquery = base_queryset.values(pk_name)[:batch_size]
        batch_qs = model.objects.filter(**{f"{pk_name}__in": pk_subquery})

        try:
            # 直接走 SQL DELETE，避免 ORM 实例化与 Collector 级联分析开销。
            deleted = batch_qs._raw_delete(using=using)
        except Exception:
            # 回退到常规 delete，确保异常场景仍可完成删除。
            logger.exception("batch_delete: _raw_delete failed, fallback to delete()")
            ids = list(base_queryset.values_list(pk_name, flat=True)[:batch_size])
            if not ids:
                break
            deleted, _ = model.objects.filter(**{f"{pk_name}__in": ids}).delete()

        if deleted <= 0:
            break
        deleted_count += deleted

    logger.info("batch_delete: deleted=%s model=%s batch_size=%s", deleted_count, model.__name__, batch_size)
    modeladmin.message_user(request, f"成功强制删除 {deleted_count} 条记录。")
batch_delete.short_description = '强制删除选中的项目'

def truncate_table(modeladmin, request, queryset):
    """清空整表（仅 superuser，二次确认）"""
    if not request.user.is_superuser:
        modeladmin.message_user(request, "仅超级管理员可执行“清空整表(慎用)”。", level=messages.ERROR)
        return None

    model = modeladmin.model
    opts = model._meta
    table_name = opts.db_table
    using = queryset.db
    conn = connections[using]

    if conn.vendor != "postgresql":
        modeladmin.message_user(request, "当前数据库非 PostgreSQL，已拒绝执行 TRUNCATE。", level=messages.ERROR)
        return None

    if request.POST.get("confirm_truncate") == "yes":
        quoted_table = conn.ops.quote_name(table_name)
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"TRUNCATE TABLE {quoted_table}")
            logger.warning(
                "truncate_table: table=%s model=%s operator=%s",
                table_name,
                model.__name__,
                request.user.username,
            )
            modeladmin.message_user(request, f"已清空整表：{table_name}", level=messages.WARNING)
        except Exception:
            logger.exception("truncate_table failed: table=%s model=%s", table_name, model.__name__)
            modeladmin.message_user(request, f"清空整表失败：{table_name}", level=messages.ERROR)
        return None

    context = {
        **modeladmin.admin_site.each_context(request),
        "title": f"确认清空整表（慎用）：{opts.verbose_name_plural}",
        "opts": opts,
        "action_name": "truncate_table",
        "action_checkbox_name": ACTION_CHECKBOX_NAME,
        "selected_ids": request.POST.getlist(ACTION_CHECKBOX_NAME),
        "select_across": request.POST.get("select_across", "0"),
        "table_name": table_name,
        "model_label": opts.verbose_name_plural,
    }
    return TemplateResponse(request, "admin/truncate_table_confirmation.html", context)
truncate_table.short_description = "清空整表(慎用)"


# ========================
# 自定义时间筛选器
# ========================
class MyDateRangePicker(admin.FieldListFilter):
    template = "admin/filters/datetime_range.html"

    FILTER_LABEL = "时间范围"
    ALL_LABEL = '全部'
    FROM_LABEL = "从"
    TO_LABEL = "到"
    BUTTON_LABEL = "应用筛选"
    CLEAR_LABEL = "清空时间范围"
    TIMEZONE_HINT = "按北京时间（Asia/Shanghai）"
    options = (
        ('15m', "15分钟内", -15 * 60),
        ('1h', "1小时内", -60 * 60),
        ('6h', "6小时内", -6 * 60 * 60),
        ('24h', "24小时内", -24 * 60 * 60),
        ('3d', "3天内", -3 * 24 * 60 * 60),
        ('7d', "7天内", -7 * 24 * 60 * 60),
        ('30d', "30天内", -30 * 24 * 60 * 60),
    )

    def __init__(self, field, request, params, model, model_admin, field_path):
        self.lookup_kwarg_since = f"{field_path}__gte"
        self.lookup_kwarg_until = f"{field_path}__lte"
        self.lookup_kwarg_preset = f"{field_path}__range"
        super().__init__(field, request, params, model, model_admin, field_path)
        self.title = self.FILTER_LABEL

        excluded = set(self.expected_parameters())
        excluded.add("p")
        self.preserved_params = []
        for key, values in request.GET.lists():
            if key in excluded:
                continue
            for value in values:
                self.preserved_params.append((key, value))

    def expected_parameters(self):
        return [self.lookup_kwarg_since, self.lookup_kwarg_until, self.lookup_kwarg_preset]

    @classmethod
    def _parse_input_datetime(cls, value):
        if isinstance(value, (list, tuple)):
            # In case duplicate query params exist, use the last non-empty value.
            for item in reversed(value):
                if item not in (None, ""):
                    value = item
                    break
            else:
                return None
        if value in (None, ""):
            return None
        raw = str(value).strip()
        dt = parse_datetime(raw)
        if dt is None:
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError(f"Invalid datetime value: {raw}")
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return timezone.localtime(dt)

    @classmethod
    def _format_input_value(cls, value):
        if value in (None, ""):
            return ""
        try:
            dt = cls._parse_input_datetime(value)
        except ValueError:
            return str(value)
        return dt.strftime("%Y-%m-%dT%H:%M")

    @staticmethod
    def _format_query_value(dt):
        return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")

    def choices(self, changelist):
        now = timezone.localtime(timezone.now())
        selected_preset = self.used_parameters.get(self.lookup_kwarg_preset)

        self.current_from = self._format_input_value(self.used_parameters.get(self.lookup_kwarg_since))
        self.current_to = self._format_input_value(self.used_parameters.get(self.lookup_kwarg_until))
        self.is_all_selected = not self.current_from and not self.current_to
        self.clear_query_string = changelist.get_query_string(
            {},
            remove=[*self.expected_parameters(), "p"],
        )

        for key, label, offset_seconds in self.options:
            start = now + timedelta(seconds=offset_seconds)
            yield {
                "selected": selected_preset == key,
                "query_string": changelist.get_query_string(
                    {
                        self.lookup_kwarg_since: self._format_query_value(start),
                        self.lookup_kwarg_until: self._format_query_value(now),
                        self.lookup_kwarg_preset: key,
                    },
                    remove=["p"],
                ),
                "display": label,
            }

    def queryset(self, request, queryset):
        try:
            dt_from = self._parse_input_datetime(self.used_parameters.get(self.lookup_kwarg_since))
            dt_to = self._parse_input_datetime(self.used_parameters.get(self.lookup_kwarg_until))
        except Exception as exc:
            logger.warning("Datetime filter parsing failed and was ignored: %s", exc)
            return queryset

        if dt_from and dt_to and dt_from > dt_to:
            dt_from, dt_to = dt_to, dt_from

        filters = {}
        if dt_from:
            filters[self.lookup_kwarg_since] = dt_from
        if dt_to:
            filters[self.lookup_kwarg_until] = dt_to

        if not filters:
            return queryset
        return queryset.filter(**filters)


# ========================
# 当前告警（不需要导出）
# ========================
@admin.register(AlarmActive)
class AlarmActiveAdmin(NoAddPermissionAdminMixin, LargeTableAdminMixin, DepotScopedAdmin):
    depot_filter_field = 'device__depot'
    list_display = ('timestamp_start_display', 'device', 'alarm_code', 'alarm_meaning', 'show_confirmed_status')
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (('timestamp_start', MyDateRangePicker), 'device', 'alarm_code', 'is_confirmed')
    actions = [batch_delete, truncate_table, batch_confirm]

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
class AlarmDataAdmin(ReadOnlyImportExportAdminMixin, LargeTableAdminMixin, DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = AlarmDataResource
    list_display = ('timestamp_start_display', 'timestamp_end_display', 'device', 'alarm_code', 'alarm_meaning', 'show_confirmed_status')
    search_fields = ('device__device_id', 'device__name', 'alarm_code')
    list_filter = (('timestamp_start', MyDateRangePicker), 'device', 'alarm_code', 'is_confirmed')
    actions = [batch_delete, truncate_table, batch_confirm]

    def get_queryset(self, request):
        return super().get_queryset(request).order_by(
            F('timestamp_end').desc(nulls_last=True),
            '-timestamp_start',
        )

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
        return obj.get_status_bits_grouped_by_byte(start_byte=4)

    def dehydrate_timestamp(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')


@admin.register(SwitchData)
class SwitchDataAdmin(ReadOnlyImportExportAdminMixin, LargeTableAdminMixin, DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = SwitchDataResource
    export_form_class = ExportForm
    list_display = ('timestamp_with_seconds', 'device', 'formatted_switch_status')
    list_filter = (('timestamp', MyDateRangePicker), 'device')
    search_fields = ('device__device_id', 'device__ip_address', 'device__name')
    actions = [batch_delete, truncate_table]

    def formatted_switch_status(self, obj):
        return obj.get_status_bits_grouped_by_byte(start_byte=4)

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
class AnalogDataAdmin(ReadOnlyImportExportAdminMixin, LargeTableAdminMixin, DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = AnalogDataResource
    list_display = ('timestamp_with_seconds', 'device', 'voltage_1', 'current_1_display', 'voltage_2', 'current_2_display')
    list_filter = (('timestamp', MyDateRangePicker), 'device')
    search_fields = ('device__device_id', 'device__ip_address', 'device__name')
    actions = [batch_delete, truncate_table]

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')

    def current_1_display(self, obj):
        return obj.current_1

    def current_2_display(self, obj):
        return obj.current_2

    current_1_display.admin_order_field = 'current_1'
    current_1_display.short_description = format_html('<span style="text-transform:none;">电流1(mA)</span>')
    current_2_display.admin_order_field = 'current_2'
    current_2_display.short_description = format_html('<span style="text-transform:none;">电流2(mA)</span>')
    timestamp_with_seconds.short_description = '时间'


# ========================
# 用户（导入导出）
# ========================
CustomUser = get_user_model()

class CustomUserResource(resources.ModelResource):
    username = fields.Field(attribute='username', column_name='用户名')
    email = fields.Field(attribute='email', column_name='邮箱')
    is_active = fields.Field(attribute='is_active', column_name='是否激活', widget=BooleanWidget())
    is_staff = fields.Field(attribute='is_staff', column_name='是否为管理员', widget=BooleanWidget())
    depots = fields.Field(
        attribute='depots',
        column_name='可管理车间',
        widget=StrictNameManyToManyWidget(Depot, field='name', separator=', ')
    )
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
            row['可管理车间'] = ''

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
    restricted_permission_fields = {'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions', 'depots'}
    resource_class = CustomUserResource
    list_display = ('username', 'email', 'is_staff', 'is_active', 'depots_display')
    search_fields = ('username', 'email')
    ordering = ('username',)
    fieldsets = UserAdmin.fieldsets + (('车间管理', {'fields': ('depots',)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (('车间管理', {'fields': ('depots',)}),)
    filter_horizontal = UserAdmin.filter_horizontal + ('depots',)
    readonly_fields = UserAdmin.readonly_fields + ('last_login', 'date_joined')

    class Media:
        css = {'all': ('admin/css/widgets.css',)}

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.exclude(is_superuser=True)

    def has_change_permission(self, request, obj=None):
        if not request.user.is_superuser:
            return False
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj=obj)

    def has_add_permission(self, request):
        if not request.user.is_superuser:
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        if not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj=obj)

    def has_import_permission(self, request):
        if not request.user.is_superuser:
            return False
        return super().has_import_permission(request)

    def _strip_restricted_fields(self, fieldsets):
        sanitized = []
        for name, options in fieldsets:
            fields = options.get('fields', ())
            if isinstance(fields, str):
                fields = (fields,)
            filtered_fields = tuple(field for field in fields if field not in self.restricted_permission_fields)
            if not filtered_fields:
                continue
            sanitized.append((name, {**options, 'fields': filtered_fields}))
        return tuple(sanitized)

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj=obj)
        if request.user.is_superuser:
            return fieldsets
        return self._strip_restricted_fields(fieldsets)

    def get_add_fieldsets(self, request):
        fieldsets = super().get_add_fieldsets(request)
        if request.user.is_superuser:
            return fieldsets
        return self._strip_restricted_fields(fieldsets)

    def depots_display(self, obj):
        if getattr(obj, "manages_all_depots", False):
            return '全部车间'
        return ', '.join(obj.depots.order_by('ordering', 'name').values_list('name', flat=True))
    depots_display.short_description = '可管理车间'


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
class UserOperationAdmin(ReadOnlyImportExportAdminMixin, LargeTableAdminMixin, DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = UserOperationResource
    list_display = ('timestamp_with_seconds', 'device', 'operation', 'username')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'operation', 'username')
    list_filter = (('timestamp', MyDateRangePicker), 'device')
    actions = [batch_delete, truncate_table]

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S')
    timestamp_with_seconds.short_description = '时间'


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
class RelayActionAdmin(ReadOnlyImportExportAdminMixin, LargeTableAdminMixin, DepotScopedAdmin, SafeImportExportModelAdmin):
    depot_filter_field = 'device__depot'
    resource_class = RelayActionResource
    list_display = ('timestamp_with_seconds', 'device', 'relay', 'action')
    search_fields = ('device__name', 'device__device_id', 'device__ip_address', 'relay', 'action')
    list_filter = (('timestamp', MyDateRangePicker), 'device')
    actions = [batch_delete, truncate_table]

    def timestamp_with_seconds(self, obj):
        return timezone.localtime(obj.timestamp).strftime('%Y-%m-%d %H:%M:%S.%f')
    timestamp_with_seconds.short_description = '时间'


# ========================
# 设备（导入导出 & 重连动作）
# ========================
class DeviceResource(resources.ModelResource):
    device_id = fields.Field(column_name='设备id', attribute='device_id')
    name = fields.Field(column_name='设备名称', attribute='name')
    depot = fields.Field(column_name='车间', attribute='depot', widget=ForeignKeyWidget(Depot, 'name'))
    line = fields.Field(column_name='线路', attribute='line', widget=ForeignKeyWidget(Line, 'name'))
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
    return create_packet(address=0x01, function_code=0x0B, unix_time=0, operation=0)


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
    autocomplete_fields = ('depot', 'line')
    list_display = (
        'device_id', 'name', 'depot', 'line', 'ip_address',
        'x_coordinate', 'y_coordinate',
        'direction1_neighbor_id', 'direction1_neighbor_direction',
        'direction2_neighbor_id', 'direction2_neighbor_direction',
        'direction1_enabled', 'direction2_enabled',
    )
    search_fields = ('device_id', 'name', 'depot__name', 'line__name', 'ip_address')
    list_filter = ('depot', 'line', 'direction1_enabled', 'direction2_enabled')
    actions = [send_reconnect_command]

    def has_import_permission(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            return False
        return super().has_import_permission(request, *args, **kwargs)


# ========================
# 文件上传（不限制权限）
# ========================
@admin.register(UploadedFile)
class UploadedFileAdmin(ReadOnlyForNonSuperuserAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'name', 'upload_time', 'file_link')
    search_fields = ('name', )
    list_filter = ('upload_time',)

    def file_link(self, obj):
        if obj.file:
            return format_html('<a href="{}" target="_blank">下载</a>', obj.file.url)
        return "-"
    file_link.short_description = '文件下载链接'
