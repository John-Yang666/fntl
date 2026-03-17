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
    AnalogData,
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
    AnalogDataSerializer,
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
from rest_framework.permissions import IsAuthenticated, AllowAny  # type: ignore
from rest_framework import status
from django.contrib.auth import get_user_model

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


def pgadmin_link_view(request):
    return render(request, "pgadmin_link.html")


def reset_periodic_tasks(request):
    PeriodicTask.objects.all().update(last_run_at=None)
    return HttpResponse("Successfully reset last_run_at for all periodic tasks")


class TopologyStatusView(View):  # 从缓存读取用于拓扑图的信息
    def get(self, request, device_id):
        topology_key = f"device_{device_id}_topology_status"
        topology_status = cache.get(topology_key)

        if topology_status:
            return JsonResponse({"topology_status": topology_status})
        else:
            return JsonResponse({"error": "No data found"}, status=404)


class AllTopologyStatusView(View):
    def get(self, request):
        devices = Device.objects.all()
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
        switch_key = f"device_{device_id}_switch_status"
        switch_status = cache.get(switch_key)

        if switch_status:
            # 将字节数据转换为 base64 编码的字符串
            encoded_switch_status = base64.b64encode(switch_status).decode("utf-8")
            return JsonResponse({"switch_status": encoded_switch_status})
        else:
            return JsonResponse({"error": "No data found"}, status=404)


class AnalogStatusView(View):  # 从缓存读取模拟量信息
    def get(self, request, device_id):
        analog_key = f"device_{device_id}_analog_status"
        analog_status = cache.get(analog_key)

        if analog_status:
            analog_status = json.loads(analog_status)
            return JsonResponse({"analog_status": analog_status})
        else:
            return JsonResponse({"error": "No data found"}, status=404)


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    filter_backends = [DjangoFilterBackend]  # 启用过滤器
    filterset_fields = ["device_id"]  # 允许通过 `device_id` 过滤
    permission_classes = [AllowAny]  # ✅ 允许匿名访问

    def get_queryset(self):
        return Device.objects.all()  # ✅ 不做用户限制

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
            device = Device.objects.get(device_id=device_id)

            # 查询邻站设备（批量）
            neighbor_ids = [device.direction1_neighbor_id, device.direction2_neighbor_id]
            neighbors = Device.objects.filter(
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
    def get(self, request, device_id: int):
        device = get_object_or_404(Device, device_id=device_id)
        return Response(
            {
                "direction1_enabled": device.direction1_enabled,
                "direction2_enabled": device.direction2_enabled,
            }
        )


class SwitchDataViewSet(viewsets.ModelViewSet):  # 从数据库读取开关量信息
    queryset = SwitchData.objects.all()
    serializer_class = SwitchDataSerializer


class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 10000


class AnalogDataViewSet(viewsets.ModelViewSet):
    queryset = AnalogData.objects.all()
    serializer_class = AnalogDataSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        "timestamp": ["gte", "lte"],
        "device": ["exact"],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        device_id = self.request.query_params.get("device")
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = queryset.order_by("-timestamp")
        return queryset


class RelayActionViewSet(viewsets.ModelViewSet):
    queryset = RelayAction.objects.all()
    serializer_class = RelayActionSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        "timestamp": ["gte", "lte"],
        "device": ["exact"],
        "device__line": ["exact"],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        device_id = self.request.query_params.get("device")
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = queryset.order_by("-timestamp")
        return queryset


class UserOperationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserOperation.objects.all()
    serializer_class = UserOperationSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        "timestamp": ["gte", "lte"],
        "device": ["exact"],
        "device__line": ["exact"],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        device_id = self.request.query_params.get("device")
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        return queryset.order_by("-timestamp")


class ActiveAlarmListView(APIView):
    def get(self, request):
        alarms = AlarmActive.objects.select_related("device").all()
        serializer = AlarmActiveSerializer(alarms, many=True)
        return Response(serializer.data)


class ConfirmAlarmView(APIView):
    def post(self, request, device_id, alarm_code):
        try:
            alarm = AlarmActive.objects.get(
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
    filterset_fields = {
        "timestamp_start": ["gte", "lte"],
        "device": ["exact"],
        "device__line": ["exact"],
        "alarm_code": ["exact"],
        "is_confirmed": ["exact"],
    }

    def get_queryset(self):
        return super().get_queryset().order_by("-timestamp_start")

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        alarm = self.get_object()
        if not alarm.is_confirmed:
            alarm.is_confirmed = True
            alarm.save(update_fields=["is_confirmed"])
        return Response({"message": "历史告警已确认"}, status=status.HTTP_200_OK)


class DeviceListView(View):  # 返回按线路分组的设备列表
    def get(self, request):
        devices = Device.objects.all().order_by("device_id")  # 按 device_id 排序
        grouped_devices = {}

        for device in devices:
            line = device.line
            if line not in grouped_devices:
                grouped_devices[line] = []

            grouped_devices[line].append(
                {
                    "device_id": device.device_id,
                    "name": device.name,
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


@method_decorator(csrf_exempt, name="dispatch")
class SySendCommandView(View):
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
            data = json.loads(request.body)

            username = data.get("username")
            cmd_type = data.get("cmd_type")

            if not User.objects.filter(username=username).exists():
                return JsonResponse(
                    {"status": "error", "message": "用户不存在，发送失败，请重新登录"},
                    status=400,
                )

            device = Device.objects.get(device_id=device_id)
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
                username=username,
            )

            # 3）通过 Kafka 丢给 sy_agent，sy_agent 写串口
            send_sy_frame_via_redis(
                device_id=device.device_id,
                addr=addr,
                frame=frame,
                command=command_tag,
                extra_meta=extra_meta,
            )

            return JsonResponse({"status": "命令已发送"})

        except Device.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": "Device not found"},
                status=404,
            )
        except Exception as e:
            return JsonResponse(
                {"status": "error", "message": str(e)},
                status=500,
            )


class UploadedFileViewSet(viewsets.ModelViewSet):
    queryset = UploadedFile.objects.all().order_by("-upload_time")
    serializer_class = UploadedFileSerializer
    parser_classes = [MultiPartParser, FormParser]


def download_file(request, pk):
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

    def get(self, request, device_id):
        device = get_object_or_404(Device, device_id=device_id)
        serializer = DeviceDetailSerializer(device)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class DeviceSwitchDataView(APIView):
    """
    GET /api/device_switch_data/<int:device_id>/
    获取设备开关数据
    """
    
    def get(self, request, device_id):
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
