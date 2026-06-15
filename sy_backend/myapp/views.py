# myapp/views.py
from rest_framework.decorators import action  # type: ignore # 确保是小写的 action
from rest_framework.response import Response  # type: ignore # 确保是大写的 Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView  # type: ignore
from rest_framework.pagination import PageNumberPagination  # type: ignore
from rest_framework import viewsets  # type: ignore

from myapp.models import (
    Device,
    SwitchData,
    AlarmActive,
    AlarmData,
    UserOperation,
    RelayAction,
    UploadedFile,
)
from myapp.serializers import (
    DeviceSerializer,
    SwitchDataSerializer,
    AlarmActiveSerializer,
    AlarmDataSerializer,
    RelayActionSerializer,
    UserOperationSerializer,
    UploadedFileSerializer,
    DeviceDetailSerializer,
)

from django.http import JsonResponse, FileResponse, Http404  # type: ignore
from django.views import View  # type: ignore
from django.views.decorators.csrf import csrf_exempt  # type: ignore
from django.utils.decorators import method_decorator  # type: ignore
from django.conf import settings  # type: ignore
from django.core.cache import cache  # type: ignore
from django.shortcuts import render, get_object_or_404  # type: ignore
from django.http import HttpResponse  # type: ignore
from django_celery_beat.models import PeriodicTask  # type: ignore
from django_filters.rest_framework import DjangoFilterBackend  # type: ignore
from rest_framework.permissions import IsAuthenticated  # type: ignore
from rest_framework import status
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework_simplejwt.authentication import JWTAuthentication
from .runtime_config import build_runtime_config_payload, save_runtime_config_values
from .tasks.cleanup_tasks import run_cleanup_export_test
import csv

from .sy_command_sender import (
    make_cmd_a1,
    make_cmd_a2,
    make_cmd_a9,
    make_cmd_aa,
    make_cmd_b2,
    make_cmd_cc,
    make_cmd_bb_named,
    make_cmd_bb,
    BB_CODES,
    send_sy_frame_via_redis,
)

import json
import base64

User = get_user_model()

FAST_COUNT_CACHE_TTL = 30
jwt_authenticator = JWTAuthentication()


def _is_truthy_query_param(value):
    return str(value).lower() not in {"0", "false", "no", "off"}


def _resolve_request_user(request):
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return user

    if hasattr(request, "_resolved_jwt_user"):
        return request._resolved_jwt_user

    try:
        auth_result = jwt_authenticator.authenticate(request)
    except Exception:
        auth_result = None

    resolved_user = auth_result[0] if auth_result else user
    request._resolved_jwt_user = resolved_user
    return resolved_user


def _require_authenticated_request_user(request):
    user = _resolve_request_user(request)
    if getattr(user, "is_authenticated", False):
        return user, None
    return None, JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)


def _filter_device_queryset_for_user(queryset, user):
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    if user.is_superuser:
        return queryset
    if hasattr(user, "managed_depots_qs"):
        depots_qs = user.managed_depots_qs()
        if depots_qs.exists():
            return queryset.filter(depot__in=depots_qs)
    return queryset.none()


def _filter_device_queryset_for_request(queryset, request):
    return _filter_device_queryset_for_user(queryset, _resolve_request_user(request))


def _filter_related_device_queryset_for_request(queryset, request, device_field="device__depot"):
    user = _resolve_request_user(request)
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    if user.is_superuser:
        return queryset
    if hasattr(user, "managed_depots_qs"):
        depots_qs = user.managed_depots_qs()
        if depots_qs.exists():
            return queryset.filter(**{f"{device_field}__in": depots_qs})
    return queryset.none()


def _apply_device_line_name_filter(queryset, request):
    line_name = request.query_params.get("device__line")
    if line_name:
        queryset = queryset.filter(device__line__name=line_name)
    return queryset


def _query_is_unfiltered(queryset):
    query = queryset.query
    return (
        len(query.where.children) == 0
        and not query.group_by
        and not query.distinct
        and query.combinator is None
        and not query.annotations
    )


def _estimated_queryset_count(queryset):
    if connection.vendor != "postgresql":
        return None
    if not _query_is_unfiltered(queryset):
        return None

    table_name = queryset.model._meta.db_table
    cache_key = f"estimated_count:{table_name}"
    cached_count = cache.get(cache_key)
    if isinstance(cached_count, int) and cached_count >= 0:
        return cached_count

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT GREATEST(reltuples::bigint, 0) FROM pg_class WHERE oid = %s::regclass",
            [table_name],
        )
        row = cursor.fetchone()

    if not row:
        return None

    estimated_count = int(row[0])
    cache.set(cache_key, estimated_count, FAST_COUNT_CACHE_TTL)
    return estimated_count


def _local_datetime_text(value):
    if value is None:
        return ""
    from django.utils import timezone

    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")


def _dated_records_export_filename(record_type):
    from django.utils import timezone

    return f"sy-{record_type}-{timezone.localdate().strftime('%Y%m%d')}.csv"


def _csv_export_response(record_type, headers, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{_dated_records_export_filename(record_type)}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response


def _list_without_count(viewset, request):
    queryset = viewset.filter_queryset(viewset.get_queryset())
    paginator = viewset.paginator
    page_size = paginator.get_page_size(request) if paginator else None
    page_size = page_size or 20

    try:
        page_number = max(int(request.query_params.get("page", "1")), 1)
    except (TypeError, ValueError):
        page_number = 1

    offset = (page_number - 1) * page_size
    serializer = viewset.get_serializer(queryset[offset:offset + page_size], many=True)
    return Response({"count": None, "results": serializer.data})


def _count_response_for_queryset(queryset):
    estimated_count = _estimated_queryset_count(queryset)
    approximate = estimated_count is not None
    total_count = estimated_count if approximate else queryset.count()
    return Response({"count": total_count, "approximate": approximate})

# =========================
# BB 命令中文名称映射表
# =========================
BB_NAME_ZH = {
    "UP_FORCE_CABLE": "上行强制电缆",
    "UP_AUTO": "上行自动",
    "DOWN_FORCE_CABLE": "下行强制电缆",
    "DOWN_AUTO": "下行自动",

    "REMOTE_START_LOCAL": "远程启动本站",
    "FORCE_A_DROP": "停用主机（A落下）",
    "FORCE_B_DROP": "停用备机（B落下）",

    "REMOTE_START_UP_FAULT1": "远程启动上行第一故障点",
    "REMOTE_START_UP_FAULT2": "远程启动上行第二故障点",
    "REMOTE_START_DOWN_FAULT1": "远程启动下行第一故障点",
    "REMOTE_START_DOWN_FAULT2": "远程启动下行第二故障点",
}


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        groups = user.groups.values_list("name", flat=True)
        permissions = user.get_all_permissions()
        return Response(
            {
                "username": user.username,
                "email": user.email,
                "groups": list(groups),
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "permissions": list(permissions),
            }
        )


def _ensure_superuser(request):
    if not request.user.is_superuser:
        return Response({"detail": "只有超级用户可以执行该操作。"}, status=status.HTTP_403_FORBIDDEN)
    return None


class RuntimeConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        permission_error = _ensure_superuser(request)
        if permission_error is not None:
            return permission_error
        return Response(build_runtime_config_payload())

    def put(self, request):
        permission_error = _ensure_superuser(request)
        if permission_error is not None:
            return permission_error

        try:
            payload = save_runtime_config_values(
                values=request.data.get("values"),
                user=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class RuntimeConfigCleanupExportTestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        permission_error = _ensure_superuser(request)
        if permission_error is not None:
            return permission_error
        return Response({"results": run_cleanup_export_test()})


def pgadmin_link_view(request):
    return render(request, "pgadmin_link.html")


def reset_periodic_tasks(request):
    PeriodicTask.objects.all().update(last_run_at=None)
    return HttpResponse("Successfully reset last_run_at for all periodic tasks")


class TopologyStatusView(View):  # 从缓存读取用于拓扑图的信息
    def get(self, request, device_id):
        _user, error_response = _require_authenticated_request_user(request)
        if error_response is not None:
            return error_response
        if not _filter_device_queryset_for_request(Device.objects.all(), request).filter(device_id=device_id).exists():
            return JsonResponse({"detail": "Not found."}, status=404)

        topology_key = f"device_{device_id}_topology_status"
        topology_status = cache.get(topology_key)

        if topology_status:
            return JsonResponse({"topology_status": topology_status})
        else:
            return JsonResponse({"error": "No data found"}, status=404)


class AllTopologyStatusView(View):
    def get(self, request):
        _user, error_response = _require_authenticated_request_user(request)
        if error_response is not None:
            return error_response

        devices = _filter_device_queryset_for_request(Device.objects.all(), request)
        topology_statuses = {}

        for device in devices:
            topology_key = f"device_{device.device_id}_topology_status"
            topology_status = cache.get(topology_key)
            if topology_status:
                topology_statuses[device.device_id] = topology_status
            else:
                topology_statuses[device.device_id] = {"error": "No data found"}

        return JsonResponse({"topology_statuses": topology_statuses})


class SwitchStatusView(View):  # 从缓存读取开关量信息
    def get(self, request, device_id):
        _user, error_response = _require_authenticated_request_user(request)
        if error_response is not None:
            return error_response
        if not _filter_device_queryset_for_request(Device.objects.all(), request).filter(device_id=device_id).exists():
            return JsonResponse({"detail": "Not found."}, status=404)

        switch_key = f"device_{device_id}_switch_status"
        switch_status = cache.get(switch_key)

        if switch_status:
            # 将字节数据转换为 base64 编码的字符串
            encoded_switch_status = base64.b64encode(switch_status).decode("utf-8")
            return JsonResponse({"switch_status": encoded_switch_status})
        else:
            return JsonResponse({"error": "No data found"}, status=404)


class DeviceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    filter_backends = [DjangoFilterBackend]  # 启用过滤器
    filterset_fields = ["device_id"]  # 允许通过 `device_id` 过滤
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _filter_device_queryset_for_request(Device.objects.all(), self.request)

    @action(detail=False, methods=["get"], url_path="retrieve_with_stations")
    def retrieve_with_stations(self, request):
        """
        根据 device_id 查询设备信息及其邻站信息
        """
        device_id = request.query_params.get("device_id")  # 从查询参数获取 device_id
        if not device_id:
            return Response({"error": "device_id is required"}, status=400)

        try:
            # 查询主设备
            device = self.get_queryset().get(device_id=device_id)

            # 查询邻站设备（批量）
            neighbor_ids = [device.direction1_neighbor_id, device.direction2_neighbor_id]
            neighbors = self.get_queryset().filter(
                device_id__in=[nid for nid in neighbor_ids if nid]
            )

            # 建立邻站 ID 和名称的映射
            neighbor_map = {neighbor.device_id: neighbor.name for neighbor in neighbors}

            # 提取邻站名称
            direction1_neighbor_name = neighbor_map.get(
                device.direction1_neighbor_id, None
            )
            direction2_neighbor_name = neighbor_map.get(
                device.direction2_neighbor_id, None
            )

            # 序列化设备数据
            device_data = self.get_serializer(device).data
            device_data.update(
                {
                    "direction1_neighbor_name": direction1_neighbor_name,
                    "direction2_neighbor_name": direction2_neighbor_name,
                }
            )

            return Response(device_data)

        except Device.DoesNotExist:
            return Response({"error": "Device not found"}, status=404)

        except ValueError:
            return Response({"error": "Invalid device_id format"}, status=400)

        except Exception as e:
            # 捕获其他未知错误
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=500,
            )


class DeviceFlagsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, device_id: int):
        device = get_object_or_404(_filter_device_queryset_for_request(Device.objects.all(), request), device_id=device_id)
        return Response(
            {
                "direction1_enabled": device.direction1_enabled,
                "direction2_enabled": device.direction2_enabled,
            }
        )


class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 10000


class SwitchDataViewSet(viewsets.ReadOnlyModelViewSet):  # 从数据库读取开关量信息
    queryset = SwitchData.objects.all()
    serializer_class = SwitchDataSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        "timestamp": ["gte", "lte"],
        "device": ["exact"],
    }

    def get_queryset(self):
        queryset = (
            _filter_related_device_queryset_for_request(super().get_queryset(), self.request)
            .select_related("device")
            .order_by("-timestamp")
        )
        device_id = self.request.query_params.get("device")
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        return _apply_device_line_name_filter(queryset, self.request)

    def list(self, request, *args, **kwargs):
        if _is_truthy_query_param(request.query_params.get("include_count", "1")):
            return super().list(request, *args, **kwargs)
        return _list_without_count(self, request)

    @action(detail=False, methods=["get"], url_path="count")
    def count(self, request):
        return _count_response_for_queryset(self.filter_queryset(self.get_queryset()))

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        rows = [
            [
                _local_datetime_text(record.timestamp),
                record.device.device_id,
                record.device.name,
                bytes(record.switch_status or b"").hex().upper(),
                " ".join(f"({idx + 1}){byte:08b}" for idx, byte in enumerate(bytes(record.switch_status or b""))),
                record.version,
            ]
            for record in queryset
        ]
        return _csv_export_response("switch-data", ["时间", "设备ID", "设备名称", "HEX", "状态字", "版本"], rows)


class RelayActionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RelayAction.objects.all()
    serializer_class = RelayActionSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        "timestamp": ["gte", "lte"],
        "device": ["exact"],
    }

    def get_queryset(self):
        queryset = _filter_related_device_queryset_for_request(super().get_queryset(), self.request)
        device_id = self.request.query_params.get("device")
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = _apply_device_line_name_filter(queryset, self.request)
        queryset = queryset.order_by("-timestamp")
        return queryset

    def list(self, request, *args, **kwargs):
        if _is_truthy_query_param(request.query_params.get("include_count", "1")):
            return super().list(request, *args, **kwargs)
        return _list_without_count(self, request)

    @action(detail=False, methods=["get"], url_path="count")
    def count(self, request):
        return _count_response_for_queryset(self.filter_queryset(self.get_queryset()))

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        rows = [
            [
                _local_datetime_text(record.timestamp),
                record.device.device_id,
                record.device.name,
                record.relay,
                record.action,
                record.source,
            ]
            for record in queryset.select_related("device")
        ]
        return _csv_export_response("relay-actions", ["时间", "设备ID", "设备名称", "继电器", "动作", "来源"], rows)


class UserOperationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserOperation.objects.all()
    serializer_class = UserOperationSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        "timestamp": ["gte", "lte"],
        "device": ["exact"],
    }

    def get_queryset(self):
        queryset = _filter_related_device_queryset_for_request(super().get_queryset(), self.request)
        device_id = self.request.query_params.get("device")
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = _apply_device_line_name_filter(queryset, self.request)
        return queryset.order_by("-timestamp")

    def list(self, request, *args, **kwargs):
        if _is_truthy_query_param(request.query_params.get("include_count", "1")):
            return super().list(request, *args, **kwargs)
        return _list_without_count(self, request)

    @action(detail=False, methods=["get"], url_path="count")
    def count(self, request):
        return _count_response_for_queryset(self.filter_queryset(self.get_queryset()))

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        rows = [
            [
                _local_datetime_text(record.timestamp),
                record.device.device_id if record.device else "",
                record.device.name if record.device else "系统级操作",
                record.function_code,
                record.operation,
                record.username or "",
            ]
            for record in queryset.select_related("device")
        ]
        return _csv_export_response("user-operations", ["时间", "设备ID", "设备名称", "操作码", "操作名称", "用户名"], rows)


class ActiveAlarmListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        alarms = _filter_related_device_queryset_for_request(
            AlarmActive.objects.select_related("device").all(),
            request,
        )
        serializer = AlarmActiveSerializer(alarms, many=True)
        return Response(serializer.data)


class ConfirmAlarmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, device_id, alarm_code):
        try:
            alarm = _filter_related_device_queryset_for_request(
                AlarmActive.objects.select_related("device").all(),
                request,
            ).get(
                device__device_id=device_id, alarm_code=alarm_code
            )
            alarm.is_confirmed = True
            alarm.save()
            return Response({"message": "告警已确认"}, status=status.HTTP_200_OK)
        except AlarmActive.DoesNotExist:
            return Response(
                {"error": "找不到告警"}, status=status.HTTP_404_NOT_FOUND
            )


class AlarmDataViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AlarmData.objects.all()
    serializer_class = AlarmDataSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        "timestamp_start": ["gte", "lte"],
        "device": ["exact"],
        "alarm_code": ["exact"],
        "is_confirmed": ["exact"],
    }

    def get_queryset(self):
        queryset = (
            _filter_related_device_queryset_for_request(super().get_queryset(), self.request)
            .select_related("device")
            .only(
                "id",
                "device",
                "device__device_id",
                "device__name",
                "alarm_code",
                "timestamp_start",
                "timestamp_end",
                "is_confirmed",
            )
            .order_by("-timestamp_start")
        )
        return _apply_device_line_name_filter(queryset, self.request)

    def list(self, request, *args, **kwargs):
        if _is_truthy_query_param(request.query_params.get("include_count", "1")):
            return super().list(request, *args, **kwargs)
        return _list_without_count(self, request)

    @action(detail=False, methods=["get"], url_path="count")
    def count(self, request):
        return _count_response_for_queryset(self.filter_queryset(self.get_queryset()))

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        rows = [
            [
                _local_datetime_text(record.timestamp_start),
                _local_datetime_text(record.timestamp_end),
                record.device.device_id,
                record.device.name,
                record.alarm_code,
                record.alarm_meaning,
                "已确认" if record.is_confirmed else "未确认",
            ]
            for record in queryset.select_related("device")
        ]
        return _csv_export_response(
            "alerts",
            ["开始时间", "结束时间", "设备ID", "设备名称", "告警码", "告警含义", "确认状态"],
            rows,
        )

    @action(detail=False, methods=["post"], url_path="bulk-confirm")
    def bulk_confirm(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list):
            return Response({"detail": "ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)

        unique_ids = [str(item) for item in dict.fromkeys(ids) if item]
        queryset = self.get_queryset().filter(id__in=unique_ids)
        scoped_count = queryset.count()
        queryset.filter(is_confirmed=False).update(is_confirmed=True)
        return Response({"confirmed": scoped_count, "skipped": max(len(unique_ids) - scoped_count, 0)})

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        alarm = self.get_object()
        if not alarm.is_confirmed:
            alarm.is_confirmed = True
            alarm.save(update_fields=["is_confirmed"])
        return Response({"message": "历史告警已确认"}, status=status.HTTP_200_OK)


class DeviceListView(View):  # 返回按线路分组的设备列表
    def get(self, request):
        _user, error_response = _require_authenticated_request_user(request)
        if error_response is not None:
            return error_response

        devices = _filter_device_queryset_for_request(
            Device.objects.select_related("line", "depot").all(),
            request,
        ).order_by("device_id")
        grouped_devices = {}

        for device in devices:
            line = device.line_name or "未配置线路"
            if line not in grouped_devices:
                grouped_devices[line] = []

            grouped_devices[line].append(
                {
                    "device_id": device.device_id,
                    "name": device.name,
                    "depot": device.depot_name or None,
                    "ip_address": device.ip_address,
                    "x_coordinate": device.x_coordinate,
                    "y_coordinate": device.y_coordinate,
                    "direction1_neighbor_id": device.direction1_neighbor_id,
                    "direction1_neighbor_direction": device.direction1_neighbor_direction,
                    "direction2_neighbor_id": device.direction2_neighbor_id,
                    "direction2_neighbor_direction": device.direction2_neighbor_direction,
                    "direction3_neighbor_id": device.direction3_neighbor_id,
                    "direction3_neighbor_direction": device.direction3_neighbor_direction,
                    # ★ 各方向启用信息
                    "direction1_enabled": device.direction1_enabled,
                    "direction2_enabled": device.direction2_enabled,
                    "direction3_enabled": device.direction3_enabled,
                }
            )

        return JsonResponse(grouped_devices)


class SySendCommandView(APIView):
    permission_classes = [IsAuthenticated]

    """
    sy 串口命令发送入口：
    - URL: /api/sy/send-command/<int:device_id>/
    - body 例：

      1）普通命令：
      {
        "username": "xxx",
        "cmd_type": "A1"
      }

      2）BB 远程控制（固定名字）：
      {
        "username": "xxx",
        "cmd_type": "BB",
        "bb_name": "UP_FORCE_CABLE"
      }

      3）BB 远程控制（自定义 code）：
      {
        "username": "xxx",
        "cmd_type": "BB",
        "bb_code": "05"   # 16进制字符串，或 5（十进制 int）
      }
    """

    def post(self, request, device_id):
        try:
            data = request.data

            cmd_type = data.get("cmd_type")

            device = get_object_or_404(
                _filter_device_queryset_for_request(Device.objects.all(), request),
                device_id=device_id,
            )
            # 对 sy 来说，addr 就是 sy 协议地址；串口信息在 sy_agent 那边配置。
            addr = device.device_id  # 或者 device.sy_addr，看你 models

            # 1）根据 cmd_type 构造帧
            if cmd_type == "A1":
                frame = make_cmd_a1(addr)
                op_name = "读取全部开关量(A1)"
                command_tag = "A1"
                extra_meta = {}
            elif cmd_type == "A2":
                frame = make_cmd_a2(addr)
                op_name = "读取单个变化开关量(A2)"
                command_tag = "A2"
                extra_meta = {}
            elif cmd_type == "A9":
                frame = make_cmd_a9(addr)
                op_name = "返回本机地址(A9)"
                command_tag = "A9"
                extra_meta = {}
            elif cmd_type == "AA":
                frame = make_cmd_aa()  # 广播校时
                op_name = "调整时间(AA)"
                command_tag = "AA"
                extra_meta = {}
            elif cmd_type == "B2":
                frame = make_cmd_b2(addr)
                op_name = "重发单个变化开关量(B2)"
                command_tag = "B2"
                extra_meta = {}
            elif cmd_type == "CC":
                frame = make_cmd_cc(addr)
                op_name = "清除变化开关量(CC)"
                command_tag = "CC"
                extra_meta = {}
            elif cmd_type == "BB":
                bb_name = data.get("bb_name")  # 如 "UP_FORCE_CABLE"
                bb_code_raw = data.get("bb_code")  # "05" / 5

                if bb_name:
                    # 使用预定义名字（在 BB_CODES 中）
                    if bb_name not in BB_CODES:
                        return JsonResponse(
                            {
                                "status": "error",
                                "message": f"未知 bb_name: {bb_name}",
                            },
                            status=400,
                        )
                    frame = make_cmd_bb_named(addr, bb_name)

                    zh_name = BB_NAME_ZH.get(bb_name, f"未知操作（{bb_name}）")
                    # 操作名称：远程控制(上行强制电缆) / 远程控制(远程启动本站) ...
                    op_name = f"远程控制（{zh_name}）"
                    command_tag = f"BB_{bb_name}"
                    extra_meta = {"bb_name": bb_name}

                elif bb_code_raw is not None:
                    # 自定义 code
                    if isinstance(bb_code_raw, str):
                        try:
                            bb_code = int(bb_code_raw, 16)
                        except ValueError:
                            return JsonResponse(
                                {
                                    "status": "error",
                                    "message": f"bb_code 格式错误: {bb_code_raw}",
                                },
                                status=400,
                            )
                    else:
                        # 兼容前端直接传十进制整数
                        bb_code = int(bb_code_raw)

                    if not (0 <= bb_code <= 0xFF):
                        return JsonResponse(
                            {
                                "status": "error",
                                "message": f"bb_code 超出范围: {bb_code}",
                            },
                            status=400,
                        )

                    frame = make_cmd_bb(addr, bb_code)
                    # 操作名称：远程控制(自定义:0x05)
                    op_name = f"远程控制（自定义:0x{bb_code:02X}）"
                    command_tag = f"BB_0x{bb_code:02X}"
                    extra_meta = {"bb_code": bb_code}
                else:
                    return JsonResponse(
                        {
                            "status": "error",
                            "message": "BB 命令需要提供 bb_name 或 bb_code",
                        },
                        status=400,
                    )
            else:
                return JsonResponse(
                    {"status": "error", "message": f"未知 cmd_type: {cmd_type}"},
                    status=400,
                )

            # 2）记录用户操作
            UserOperation.objects.create(
                device=device,
                function_code=cmd_type,
                operation=op_name,
                username=request.user.username,
            )

            # 3）通过 Redis Streams 丢给 sy_agent，sy_agent 写串口
            send_sy_frame_via_redis(
                device_id=device.device_id,
                addr=addr,
                frame=frame,
                command=command_tag,
                extra_meta=extra_meta,
            )

            return JsonResponse({"status": "命令已发送"})

        except Http404:
            raise
        except Exception as e:
            return JsonResponse(
                {"status": "error", "message": str(e)},
                status=500,
            )


class UploadedFileViewSet(viewsets.ModelViewSet):
    queryset = UploadedFile.objects.all().order_by("-upload_time")
    serializer_class = UploadedFileSerializer
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        permission_error = _ensure_superuser(request)
        if permission_error is not None:
            return permission_error
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        permission_error = _ensure_superuser(request)
        if permission_error is not None:
            return permission_error
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        permission_error = _ensure_superuser(request)
        if permission_error is not None:
            return permission_error
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        permission_error = _ensure_superuser(request)
        if permission_error is not None:
            return permission_error
        return super().destroy(request, *args, **kwargs)


def download_file(request, pk):
    _user, error_response = _require_authenticated_request_user(request)
    if error_response is not None:
        return error_response
    try:
        file_obj = UploadedFile.objects.get(pk=pk)
        return FileResponse(
            file_obj.file.open(), as_attachment=True, filename=file_obj.name
        )
    except UploadedFile.DoesNotExist:
        raise Http404


# for sy
class DeviceDetailView(APIView):
    """
    GET /api/device-detail/<int:device_id>/
    返回设备基础信息 + 最新 A1 快照 + 最近一条 A2 变化
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        device = get_object_or_404(_filter_device_queryset_for_request(Device.objects.all(), request), device_id=device_id)
        serializer = DeviceDetailSerializer(device)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class DeviceSwitchDataView(APIView):
    """
    GET /api/device_switch_data/<int:device_id>/
    获取设备开关数据
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        get_object_or_404(_filter_device_queryset_for_request(Device.objects.all(), request), device_id=device_id)
        switch_status = cache.get(f"device_{device_id}_switch_status")
        if not switch_status:
            return Response({"detail": "数据未找到或已过期"}, status=status.HTTP_404_NOT_FOUND)

        if isinstance(switch_status, memoryview):
            switch_status = switch_status.tobytes()
        elif isinstance(switch_status, bytearray):
            switch_status = bytes(switch_status)

        if isinstance(switch_status, (bytes, bytearray)):
            updated_at = cache.get(f"device_{device_id}_switch_status_updated_at")
            version = cache.get(f"device_{device_id}_switch_status_version") or "v4"
            return Response(
                {
                    "timestamp": updated_at,
                    "version": version,
                    "hex": bytes(switch_status).hex().upper(),
                },
                status=status.HTTP_200_OK,
            )

        return Response(switch_status, status=status.HTTP_200_OK)
