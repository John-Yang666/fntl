#myapp/views.py
from rest_framework.decorators import action  # type: ignore # 确保是小写的 action
from rest_framework.response import Response  # type: ignore # 确保是大写的 Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView # type: ignore
from rest_framework.pagination import PageNumberPagination # type: ignore
from rest_framework import viewsets # type: ignore
from myapp.models import Device, SwitchData, AnalogData, AlarmActive, AlarmData, UserOperation, RelayAction, UploadedFile, HelpFaqEntry
from myapp.serializers import DeviceSerializer, SwitchDataSerializer, AlarmActiveSerializer, AnalogDataSerializer, AlarmDataSerializer, RelayActionSerializer, UserOperationSerializer, UploadedFileSerializer, HelpFaqEntrySerializer, HelpFaqEntryWriteSerializer
from django.http import JsonResponse, FileResponse, Http404 # type: ignore
from django.views import View # type: ignore
from django.views.decorators.csrf import csrf_exempt # type: ignore
from django.utils.decorators import method_decorator # type: ignore
from django.conf import settings # type: ignore
from .udp_sender import create_packet, send_packet  # 导入函数
from django.core.cache import cache # type: ignore
import json
import base64
import redis
from datetime import datetime
import time
#import paho.mqtt.client as mqtt
from django.shortcuts import render, get_object_or_404 # type: ignore
from django.http import HttpResponse # type: ignore
from django.utils import timezone
from django_celery_beat.models import PeriodicTask # type: ignore
from django_filters.rest_framework import DjangoFilterBackend # type: ignore
from rest_framework.permissions import IsAuthenticated # type: ignore
from rest_framework import status
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework_simplejwt.authentication import JWTAuthentication
from .runtime_config import (
    build_runtime_config_payload,
    get_communication_timeout,
    save_runtime_config_values,
)
from .tasks.cleanup_tasks import run_cleanup_export_test
import csv

User = get_user_model()

FAST_COUNT_CACHE_TTL = 30
redis_comm_client = redis.StrictRedis(host='redis', port=6379, db=2, decode_responses=True)
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
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")


def _dated_records_export_filename(record_type):
    return f"bt-{record_type}-{timezone.localdate().strftime('%Y%m%d')}.csv"


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


def _parse_iso_aware(value: str):
    dt = datetime.fromisoformat(value)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone=timezone.utc)
    return dt


def _is_device_comm_online(device_id: int) -> bool:
    raw_time = redis_comm_client.get(f"device_{device_id}_last_communication_time")
    raw_monotonic = redis_comm_client.get(f"device_{device_id}_last_communication_monotonic")
    if not raw_time:
        return False

    now = timezone.now()
    now_monotonic = time.monotonic()

    if raw_monotonic is not None:
        try:
            elapsed = now_monotonic - float(raw_monotonic)
            if elapsed < 0:
                elapsed = 0.0
            return elapsed <= get_communication_timeout()
        except (TypeError, ValueError):
            pass

    try:
        last_comm = _parse_iso_aware(raw_time)
    except Exception:
        return False

    return (now - last_comm).total_seconds() <= get_communication_timeout()


def _ensure_superuser(request):
    if not request.user.is_superuser:
        return Response({"detail": "只有超级用户可以执行该操作。"}, status=status.HTTP_403_FORBIDDEN)
    return None

class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        groups = user.groups.values_list('name', flat=True)
        permissions = user.get_all_permissions()
        return Response({
            'username': user.username,
            'email': user.email,
            'groups': list(groups),
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'permissions': list(permissions)
        })


class HelpFaqView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = HelpFaqEntry.objects.all().order_by('display_order', 'id')
        serializer = HelpFaqEntrySerializer(items, many=True)
        return Response(serializer.data)

    def put(self, request):
        permission_error = _ensure_superuser(request)
        if permission_error is not None:
            return permission_error

        serializer = HelpFaqEntryWriteSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        payload = serializer.validated_data
        existing_items = {item.id: item for item in HelpFaqEntry.objects.all()}
        keep_ids = set()

        with transaction.atomic():
            for index, item_data in enumerate(payload, start=1):
                item_id = item_data.get('id')
                title = item_data['title']
                content = item_data['content']

                if item_id and item_id in existing_items:
                    faq_item = existing_items[item_id]
                    faq_item.title = title
                    faq_item.content = content
                    faq_item.display_order = index
                    faq_item.save(update_fields=['title', 'content', 'display_order', 'updated_at'])
                    keep_ids.add(faq_item.id)
                else:
                    faq_item = HelpFaqEntry.objects.create(
                        title=title,
                        content=content,
                        display_order=index,
                    )
                    keep_ids.add(faq_item.id)

            if keep_ids:
                HelpFaqEntry.objects.exclude(id__in=keep_ids).delete()
            else:
                HelpFaqEntry.objects.all().delete()

        items = HelpFaqEntry.objects.all().order_by('display_order', 'id')
        return Response(HelpFaqEntrySerializer(items, many=True).data)


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
                file_values=request.data.get("file_values"),
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
    return render(request, 'pgadmin_link.html')

# MQTT配置
#MQTT_BROKER = "localhost"
#MQTT_PORT = 1883
#MQTT_TOPIC_COMMAND = "devices/command"

# 初始化 MQTT 客户端
#mqtt_client = mqtt.Client()
#mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
#mqtt_client.loop_start()

def reset_periodic_tasks(request):
    PeriodicTask.objects.all().update(last_run_at=None)
    return HttpResponse("Successfully reset last_run_at for all periodic tasks")

class TopologyStatusView(View):#从缓存读取用于拓扑图的信息
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

class SwitchStatusView(View):#从缓存读取开关量信息
    def get(self, request, device_id):
        _user, error_response = _require_authenticated_request_user(request)
        if error_response is not None:
            return error_response
        if not _filter_device_queryset_for_request(Device.objects.all(), request).filter(device_id=device_id).exists():
            return JsonResponse({"detail": "Not found."}, status=404)

        if not _is_device_comm_online(device_id):
            cache.delete(f"device_{device_id}_switch_status")
            return JsonResponse({"error": "Device offline"}, status=404)

        switch_key = f"device_{device_id}_switch_status"
        switch_status = cache.get(switch_key)

        if switch_status is None:
            latest_switch = (
                SwitchData.objects
                .filter(device_id=device_id)
                .order_by("-timestamp")
                .values("switch_status")
                .first()
            )
            if latest_switch:
                switch_status = bytes(latest_switch["switch_status"])
                cache.set(switch_key, switch_status, timeout=None)

        if switch_status:
            encoded_switch_status = base64.b64encode(switch_status).decode('utf-8')
            return JsonResponse({"switch_status": encoded_switch_status})

        return JsonResponse({"error": "No data found"}, status=404)

class AnalogStatusView(View):# 从缓存读取模拟量信息
    def get(self, request, device_id):
        _user, error_response = _require_authenticated_request_user(request)
        if error_response is not None:
            return error_response
        if not _filter_device_queryset_for_request(Device.objects.all(), request).filter(device_id=device_id).exists():
            return JsonResponse({"detail": "Not found."}, status=404)

        analog_key = f"device_{device_id}_analog_status"
        analog_status = cache.get(analog_key)
        
        if analog_status:
            analog_status = json.loads(analog_status)
            return JsonResponse({"analog_status": analog_status})
        else:
            return JsonResponse({"error": "No data found"}, status=404)

class DeviceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    filter_backends = [DjangoFilterBackend]  # 启用过滤器
    filterset_fields = ['device_id']  # 允许通过 `device_id` 过滤
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _filter_device_queryset_for_request(Device.objects.all(), self.request)

    '''def get_queryset(self):
        user = self.request.user

        # 允许匿名用户访问公开设备，或返回空集
        if not user.is_authenticated:
            # ✅ 方式一：只返回公共设备（如 depot 为 "公共"）
            return Device.objects.filter(depot="公共")

            # ✅ 方式二：完全不返回（空结果）
            # return Device.objects.none()

        # 超管能看全部
        if user.is_superuser:
            return Device.objects.all()

        # 登录用户且有 depot 权限
        if hasattr(user, 'depots') and isinstance(user.depots, list):
            return Device.objects.filter(depot__in=user.depots)

        # 登录用户但没 depot 字段或结构错误
        return Device.objects.none()'''

    @action(detail=False, methods=['get'], url_path='retrieve_with_stations')
    def retrieve_with_stations(self, request):
        """
        根据 device_id 查询设备信息及其邻站信息
        """
        device_id = request.query_params.get('device_id')  # 从查询参数获取 device_id
        if not device_id:
            return Response({'error': 'device_id is required'}, status=400)

        try:
            # 查询主设备
            device = self.get_queryset().get(device_id=device_id)

            # 查询邻站设备（批量）
            neighbor_ids = [device.direction1_neighbor_id, device.direction2_neighbor_id]
            neighbors = self.get_queryset().filter(device_id__in=[nid for nid in neighbor_ids if nid])

            # 建立邻站 ID 和名称的映射
            neighbor_map = {neighbor.device_id: neighbor.name for neighbor in neighbors}

            # 提取邻站名称
            direction1_neighbor_name = neighbor_map.get(device.direction1_neighbor_id, None)
            direction2_neighbor_name = neighbor_map.get(device.direction2_neighbor_id, None)

            # 序列化设备数据
            device_data = self.get_serializer(device).data
            device_data.update({
                'direction1_neighbor_name': direction1_neighbor_name,
                'direction2_neighbor_name': direction2_neighbor_name,
            })

            return Response(device_data)

        except Device.DoesNotExist:
            return Response({'error': 'Device not found'}, status=404)

        except ValueError:
            return Response({'error': 'Invalid device_id format'}, status=400)

        except Exception as e:
            # 捕获其他未知错误
            return Response({'error': f'An unexpected error occurred: {str(e)}'}, status=500)

class DeviceFlagsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, device_id: int):
        device = get_object_or_404(_filter_device_queryset_for_request(Device.objects.all(), request), device_id=device_id)
        return Response({
            "direction1_enabled": device.direction1_enabled,
            "direction2_enabled": device.direction2_enabled,
        })

class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 10000

class SwitchDataViewSet(viewsets.ReadOnlyModelViewSet):# 从数据库读取开关量信息
    queryset = SwitchData.objects.all()
    serializer_class = SwitchDataSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        'timestamp': ['gte', 'lte'],
        'device': ['exact'],
    }

    def get_queryset(self):
        queryset = (
            _filter_related_device_queryset_for_request(super().get_queryset(), self.request)
            .select_related("device")
            .order_by("-timestamp")
        )
        device_id = self.request.query_params.get('device')
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
                record.get_status_bits_grouped_by_byte(start_byte=4),
                bytes(record.switch_status or b"").hex().upper(),
            ]
            for record in queryset
        ]
        return _csv_export_response("switch-data", ["时间", "设备ID", "设备名称", "开关量", "HEX"], rows)

class AnalogDataViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AnalogData.objects.all()
    serializer_class = AnalogDataSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        'timestamp': ['gte', 'lte'],
        'device': ['exact']
    }

    def get_queryset(self):
        queryset = _filter_related_device_queryset_for_request(
            super().get_queryset(),
            self.request,
        ).select_related("device")
        device_id = self.request.query_params.get('device')
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = _apply_device_line_name_filter(queryset, self.request)
        queryset = queryset.order_by('-timestamp')
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
                record.voltage_1,
                record.current_1,
                record.voltage_2,
                record.current_2,
            ]
            for record in queryset
        ]
        return _csv_export_response(
            "analog-data",
            ["时间", "设备ID", "设备名称", "电压1(V)", "电流1(mA)", "电压2(V)", "电流2(mA)"],
            rows,
        )
    
class RelayActionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RelayAction.objects.all()
    serializer_class = RelayActionSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        'timestamp': ['gte', 'lte'],
        'device': ['exact'],
    }
    def get_queryset(self):
        queryset = _filter_related_device_queryset_for_request(super().get_queryset(), self.request)
        device_id = self.request.query_params.get('device')
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = _apply_device_line_name_filter(queryset, self.request)
        queryset = queryset.order_by('-timestamp')
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
            ]
            for record in queryset.select_related("device")
        ]
        return _csv_export_response("relay-actions", ["时间", "设备ID", "设备名称", "继电器", "动作"], rows)

class UserOperationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserOperation.objects.all()
    serializer_class = UserOperationSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        'timestamp': ['gte', 'lte'],
        'device': ['exact'],
    }

    def get_queryset(self):
        queryset = _filter_related_device_queryset_for_request(super().get_queryset(), self.request)
        device_id = self.request.query_params.get('device')
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = _apply_device_line_name_filter(queryset, self.request)
        return queryset.order_by('-timestamp')

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
            AlarmActive.objects.select_related('device').all(),
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
            ).get(device__device_id=device_id, alarm_code=alarm_code)
            alarm.is_confirmed = True
            alarm.save()
            return Response({'message': '告警已确认'}, status=status.HTTP_200_OK)
        except AlarmActive.DoesNotExist:
            return Response({'error': '找不到告警'}, status=status.HTTP_404_NOT_FOUND)
    
class AlarmDataViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AlarmData.objects.all()
    serializer_class = AlarmDataSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_fields = {
        'timestamp_start': ['gte', 'lte'],
        'device': ['exact'],
        'alarm_code': ['exact'],
        'is_confirmed': ['exact'],
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

    @action(detail=False, methods=['post'], url_path='bulk-confirm')
    def bulk_confirm(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list):
            return Response({"detail": "ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)

        unique_ids = [str(item) for item in dict.fromkeys(ids) if item]
        queryset = self.get_queryset().filter(id__in=unique_ids)
        scoped_count = queryset.count()
        queryset.filter(is_confirmed=False).update(is_confirmed=True)
        return Response({"confirmed": scoped_count, "skipped": max(len(unique_ids) - scoped_count, 0)})

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        alarm = self.get_object()
        if not alarm.is_confirmed:
            alarm.is_confirmed = True
            alarm.save(update_fields=['is_confirmed'])
        return Response({'message': '历史告警已确认'}, status=status.HTTP_200_OK)

'''class AlertsAmountView(APIView):
    def get(self, request):
        count = cache.get("alerts_amount", 0)  # 默认为 0
        return Response({'alerts_amount': count})'''

class DeviceListView(View):  # 返回按线路分组的设备列表
    def get(self, request):
        _user, error_response = _require_authenticated_request_user(request)
        if error_response is not None:
            return error_response

        devices = _filter_device_queryset_for_request(
            Device.objects.select_related("line", "depot").all(),
            request,
        ).order_by('device_id')
        grouped_devices = {}

        for device in devices:
            line = device.line_name or "未配置线路"
            if line not in grouped_devices:
                grouped_devices[line] = []
            grouped_devices[line].append({
                'device_id': device.device_id,
                'name': device.name,
                'depot': device.depot_name or None,
                'ip_address': device.ip_address,
                'x_coordinate': device.x_coordinate,
                'y_coordinate': device.y_coordinate,
                'direction1_neighbor_id': device.direction1_neighbor_id,
                'direction1_neighbor_direction': device.direction1_neighbor_direction,
                'direction2_neighbor_id': device.direction2_neighbor_id,
                'direction2_neighbor_direction': device.direction2_neighbor_direction,
            })

        return JsonResponse(grouped_devices)
     
class SendCommandView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        try:
            data = request.data
            function_code = data.get('function_code')
            unix_time = data.get('time')
            operation = data.get('operation')
            is_custom_command = bool(data.get('is_custom_command'))

            # 根据设备ID获取设备信息
            device = get_object_or_404(
                _filter_device_queryset_for_request(Device.objects.all(), request),
                device_id=device_id,
            )
            udp_target_ip = device.ip_address
            packet = create_packet(device.device_id, function_code, unix_time, operation)

            # 操作转换
            direction_mapping = {
                1: '一方向',
                2: '二方向',
            }
            mode_mapping = {
                1: '强制电缆',
                2: '自动',
                3: '强制光缆',
            }
            operation_mapping = {
                0: '重启网管板'
            }

            try:
                function_code_value = int(function_code)
            except (TypeError, ValueError):
                function_code_value = None

            try:
                operation_value = int(operation)
            except (TypeError, ValueError):
                operation_value = None

            direction_label = direction_mapping.get(function_code_value)
            if is_custom_command and function_code_value is not None:
                operation_name = f'自定义命令 0x{function_code_value & 0xFF:02X}'
            elif direction_label:
                mode_label = mode_mapping.get(operation_value, '未知操作')
                operation_name = f'{direction_label}{mode_label}'
            else:
                operation_name = operation_mapping.get(operation_value, '未知操作')

            # 添加操作记录
            UserOperation.objects.create(
                device=device,
                function_code=function_code,
                operation=operation_name,
                username=request.user.username
            )

            # 使用 Redis 发送数据包
            send_packet(packet, udp_target_ip)

            # 发布MQTT消息
            #payload = {
            #    'device_id': device_id,
            #    'function_code': function_code,
            #    'time': unix_time,
            #    'operation': operation,
            #    'packet': packet.hex()#udp_sender中的create_packet生成的数据
            #}
            #mqtt_client.publish(MQTT_TOPIC_COMMAND, json.dumps(payload), qos = 1)# 设置QoS为1, 至少一次，可能重复，适用于允许消息重复但不允许消息丢失的场景。

            return JsonResponse({'status': '命令已发送'})
        except Http404:
            raise
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
        
class UploadedFileViewSet(viewsets.ModelViewSet):
    queryset = UploadedFile.objects.all().order_by('-upload_time')
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
        return FileResponse(file_obj.file.open(), as_attachment=True, filename=file_obj.name)
    except UploadedFile.DoesNotExist:
        raise Http404
