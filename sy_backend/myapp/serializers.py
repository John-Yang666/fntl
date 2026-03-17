from rest_framework import serializers
from django.utils import timezone
from myapp.models import Device, SwitchData, AlarmActive, AnalogData, RelayAction, AlarmData, UserOperation, UploadedFile, ChangeBitEvent

class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = '__all__'

class SwitchDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = SwitchData
        fields = '__all__'

class AlarmActiveSerializer(serializers.ModelSerializer):
    device_id = serializers.IntegerField(source='device.device_id')
    device_name = serializers.CharField(source='device.name')
    alarm_meaning = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source='timestamp_start')
    confirmed = serializers.BooleanField(source='is_confirmed')  # 显式映射字段名

    class Meta:
        model = AlarmActive
        fields = ['device_id', 'device_name', 'alarm_code', 'alarm_meaning', 'timestamp', 'confirmed']

    def get_alarm_meaning(self, obj):
        return obj.alarm_meaning
    
class AnalogDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalogData
        fields = '__all__'

class RelayActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RelayAction
        fields = '__all__'

class UserOperationSerializer(serializers.ModelSerializer):
    device_id = serializers.IntegerField(source='device.device_id', read_only=True)
    device_name = serializers.CharField(source='device.name', read_only=True)

    class Meta:
        model = UserOperation
        fields = [
            'id',
            'device_id',
            'device_name',
            'function_code',
            'operation',
            'username',
            'timestamp',
        ]

class AlarmDataSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    device_id = serializers.IntegerField(source='device.device_id', read_only=True)
    device_name = serializers.CharField(source='device.name', read_only=True)
    alarm_meaning = serializers.CharField(read_only=True)
    timestamp = serializers.DateTimeField(source='timestamp_start')
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = AlarmData
        fields = [
            'id',
            'device_id',
            'device_name',
            'alarm_code',
            'alarm_meaning',
            'timestamp',
            'timestamp_end',
            'is_confirmed',
            'duration_seconds',
        ]

    def get_duration_seconds(self, obj):
        end_time = obj.timestamp_end or timezone.now()
        duration = (end_time - obj.timestamp_start).total_seconds()
        return max(int(duration), 0)

class UploadedFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = '__all__'

# ========================
# 以下为为sy设备添加的
# latest_switch：最新一条 A1 快照（状态字），带 HEX 和时间
#latest_change：最新一条 A2 变化量事件（方便你后面在前端做“最近一次变化”显示）

class SwitchDataSimpleSerializer(serializers.ModelSerializer):
    hex = serializers.SerializerMethodField()

    class Meta:
        model = SwitchData
        fields = ["timestamp", "version", "hex"]

    def get_hex(self, obj):
        b = bytes(obj.switch_status or b"")
        return b.hex().upper()


class ChangeBitEventSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChangeBitEvent
        fields = ["timestamp", "bit_index", "value", "source"]


class DeviceDetailSerializer(serializers.ModelSerializer):
    latest_switch = serializers.SerializerMethodField()
    latest_change = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            "device_id",
            "name",
            "depot",
            "line",
            "ip_address",
            "direction1_enabled",
            "direction2_enabled",
            "direction3_enabled",
            "supports_auto_switch",
            "x_coordinate",
            "y_coordinate",
            "direction1_neighbor_id",
            "direction1_neighbor_direction",
            "direction2_neighbor_id",
            "direction2_neighbor_direction",
            "remark",
            "latest_switch",
            "latest_change",
        ]

    def get_latest_switch(self, obj):
        qs = SwitchData.objects.filter(device=obj).order_by("-timestamp")
        sd = qs.first()
        if not sd:
            return None
        return SwitchDataSimpleSerializer(sd).data

    def get_latest_change(self, obj):
        qs = ChangeBitEvent.objects.filter(device=obj).order_by("-timestamp")
        ev = qs.first()
        if not ev:
            return None
        return ChangeBitEventSimpleSerializer(ev).data
