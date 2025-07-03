#myapp/views.py
from rest_framework.decorators import action  # type: ignore # 确保是小写的 action
from rest_framework.response import Response  # type: ignore # 确保是大写的 Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView # type: ignore
from rest_framework.pagination import PageNumberPagination # type: ignore
from rest_framework import viewsets # type: ignore
from myapp.models import Device, SwitchData, AnalogData, AlarmActive, AlarmData, UserOperation, RelayAction, UploadedFile
from myapp.serializers import DeviceSerializer, SwitchDataSerializer, AlarmActiveSerializer, AnalogDataSerializer, AlarmDataSerializer, RelayActionSerializer, UploadedFileSerializer
from django.http import JsonResponse, FileResponse, Http404 # type: ignore
from django.views import View # type: ignore
from django.views.decorators.csrf import csrf_exempt # type: ignore
from django.utils.decorators import method_decorator # type: ignore
from django.conf import settings # type: ignore
from .udp_sender import create_packet, send_packet_via_kafka  # 导入函数
from django.core.cache import cache # type: ignore
import json
import base64
#import paho.mqtt.client as mqtt
from django.shortcuts import render # type: ignore
from django.http import HttpResponse # type: ignore
from django_celery_beat.models import PeriodicTask # type: ignore
from django_filters.rest_framework import DjangoFilterBackend # type: ignore
from rest_framework.permissions import IsAuthenticated, AllowAny # type: ignore
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()

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

class SwitchStatusView(View):#从缓存读取开关量信息
    def get(self, request, device_id):
        switch_key = f"device_{device_id}_switch_status"
        switch_status = cache.get(switch_key)
        
        if switch_status:
            # 将字节数据转换为 base64 编码的字符串
            encoded_switch_status = base64.b64encode(switch_status).decode('utf-8')
            return JsonResponse({"switch_status": encoded_switch_status})
        else:
            return JsonResponse({"error": "No data found"}, status=404)

class AnalogStatusView(View):# 从缓存读取模拟量信息
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
    filterset_fields = ['device_id']  # 允许通过 `device_id` 过滤
    permission_classes = [AllowAny]  # ✅ 允许匿名访问

    def get_queryset(self):
        return Device.objects.all()  # ✅ 不做用户限制

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
            device = Device.objects.get(device_id=device_id)

            # 查询邻站设备（批量）
            neighbor_ids = [device.direction1_neighbor_id, device.direction2_neighbor_id]
            neighbors = Device.objects.filter(device_id__in=[nid for nid in neighbor_ids if nid])

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



class SwitchDataViewSet(viewsets.ModelViewSet):# 从数据库读取开关量信息
    queryset = SwitchData.objects.all()
    serializer_class = SwitchDataSerializer

class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 10000

class AnalogDataViewSet(viewsets.ModelViewSet):
    queryset = AnalogData.objects.all()
    serializer_class = AnalogDataSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        'timestamp': ['gte', 'lte'],
        'device': ['exact']
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        device_id = self.request.query_params.get('device')
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = queryset.order_by('-timestamp')
        return queryset
    
class RelayActionViewSet(viewsets.ModelViewSet):
    queryset = RelayAction.objects.all()
    serializer_class = RelayActionSerializer
    pagination_class = CustomPageNumberPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        'timestamp': ['gte', 'lte'],
        'device': ['exact']
    }
    def get_queryset(self):
        queryset = super().get_queryset()
        device_id = self.request.query_params.get('device')
        if device_id is not None:
            queryset = queryset.filter(device_id=device_id)
        queryset = queryset.order_by('-timestamp')
        return queryset

class ActiveAlarmListView(APIView):
    def get(self, request):
        alarms = AlarmActive.objects.select_related('device').all()
        serializer = AlarmActiveSerializer(alarms, many=True)
        return Response(serializer.data)
    
class ConfirmAlarmView(APIView):
    def post(self, request, device_id, alarm_code):
        try:
            alarm = AlarmActive.objects.get(device__device_id=device_id, alarm_code=alarm_code)
            alarm.is_confirmed = True
            alarm.save()
            return Response({'message': '告警已确认'}, status=status.HTTP_200_OK)
        except AlarmActive.DoesNotExist:
            return Response({'error': '找不到告警'}, status=status.HTTP_404_NOT_FOUND)
    
class AlarmDataViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AlarmData.objects.all()
    serializer_class = AlarmDataSerializer

class AlertsAmountView(APIView):
    def get(self, request):
        count = cache.get("alerts_amount", 0)  # 默认为 0
        return Response({'alerts_amount': count})

class DeviceListView(View):  # 返回按线路分组的设备列表
    def get(self, request):
        devices = Device.objects.all().order_by('device_id')  # 按 device_id 排序
        grouped_devices = {}

        for device in devices:
            line = device.line
            if line not in grouped_devices:
                grouped_devices[line] = []
            grouped_devices[line].append({
                'device_id': device.device_id,
                'name': device.name,
                'ip_address': device.ip_address,
                'x_coordinate': device.x_coordinate,
                'y_coordinate': device.y_coordinate,
                'direction1_neighbor_id': device.direction1_neighbor_id,
                'direction1_neighbor_direction': device.direction1_neighbor_direction,
                'direction2_neighbor_id': device.direction2_neighbor_id,
                'direction2_neighbor_direction': device.direction2_neighbor_direction,
            })

        return JsonResponse(grouped_devices)
     
@method_decorator(csrf_exempt, name='dispatch')
class SendCommandView(View):
    def post(self, request, device_id):
        try:
            data = json.loads(request.body)
            username = data.get('username')  # 从前端获取用户名
            function_code = data.get('function_code')
            unix_time = data.get('time')
            operation = data.get('operation')

            # 验证用户名是否存在
            if not User.objects.filter(username=username).exists():
                return JsonResponse({'status': 'error', 'message': '用户不存在，发送失败，请重新登录'}, status=400)

            # 根据设备ID获取设备信息
            device = Device.objects.get(device_id=device_id)
            udp_target_ip = device.ip_address
            packet = create_packet(device.device_id, function_code, unix_time, operation)

            # 操作转换
            operation_mapping = {
                1: '强制电缆',
                2: '自动',
                3: '强制光缆',
                0: '重启网管板'
            }
            operation_name = operation_mapping.get(operation, '未知操作')

            # 添加操作记录
            UserOperation.objects.create(
                device=device,
                function_code=function_code,
                operation=operation_name,
                username=username
            )

            # 使用 Redis 发送数据包
            send_packet_via_kafka(packet, udp_target_ip)

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
        except Device.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Device not found'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
        
class UploadedFileViewSet(viewsets.ModelViewSet):
    queryset = UploadedFile.objects.all().order_by('-upload_time')
    serializer_class = UploadedFileSerializer
    parser_classes = [MultiPartParser, FormParser]

def download_file(request, pk):
    try:
        file_obj = UploadedFile.objects.get(pk=pk)
        return FileResponse(file_obj.file.open(), as_attachment=True, filename=file_obj.name)
    except UploadedFile.DoesNotExist:
        raise Http404
