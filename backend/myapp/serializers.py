from rest_framework import serializers
from django.utils import timezone
from myapp.models import Device, SwitchData, AlarmActive, AnalogData, RelayAction, AlarmData, UserOperation, UploadedFile, HelpFaqEntry

class DeviceSerializer(serializers.ModelSerializer):
    depot = serializers.SerializerMethodField()
    line = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            'id',
            'device_id',
            'name',
            'depot',
            'line',
            'ip_address',
            'x_coordinate',
            'y_coordinate',
            'direction1_neighbor_id',
            'direction1_neighbor_direction',
            'direction2_neighbor_id',
            'direction2_neighbor_direction',
            'remark',
            'alarm_filters',
            'direction1_enabled',
            'direction2_enabled',
        ]

    def get_depot(self, obj):
        return obj.depot_name or None

    def get_line(self, obj):
        return obj.line_name or None

class SwitchDataSerializer(serializers.ModelSerializer):
    device_id = serializers.IntegerField(source='device.device_id', read_only=True)
    device_name = serializers.CharField(source='device.name', read_only=True)
    switch_status_text = serializers.SerializerMethodField()
    switch_status_hex = serializers.SerializerMethodField()

    class Meta:
        model = SwitchData
        fields = [
            'id',
            'device',
            'device_id',
            'device_name',
            'switch_status',
            'switch_status_text',
            'switch_status_hex',
            'timestamp',
        ]

    def get_switch_status_text(self, obj):
        return obj.get_status_bits_grouped_by_byte(start_byte=4)

    def get_switch_status_hex(self, obj):
        return bytes(obj.switch_status or b'').hex().upper()

class AlarmActiveSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    device_id = serializers.IntegerField(source='device.device_id')
    device_name = serializers.CharField(source='device.name')
    alarm_meaning = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source='timestamp_start')
    confirmed = serializers.BooleanField(source='is_confirmed')  # 显式映射字段名

    class Meta:
        model = AlarmActive
        fields = ['id', 'device_id', 'device_name', 'alarm_code', 'alarm_meaning', 'timestamp', 'confirmed']

    def get_alarm_meaning(self, obj):
        return obj.alarm_meaning
    
class AnalogDataSerializer(serializers.ModelSerializer):
    device_id = serializers.IntegerField(source='device.device_id', read_only=True)
    device_name = serializers.CharField(source='device.name', read_only=True)

    class Meta:
        model = AnalogData
        fields = [
            'id',
            'device',
            'device_id',
            'device_name',
            'voltage_1',
            'current_1',
            'voltage_2',
            'current_2',
            'timestamp',
        ]

class RelayActionSerializer(serializers.ModelSerializer):
    device_id = serializers.IntegerField(source='device.device_id', read_only=True)
    device_name = serializers.CharField(source='device.name', read_only=True)

    class Meta:
        model = RelayAction
        fields = [
            'id',
            'device',
            'device_id',
            'device_name',
            'relay',
            'action',
            'timestamp',
        ]

class UserOperationSerializer(serializers.ModelSerializer):
    device_id = serializers.IntegerField(source='device.device_id', read_only=True, allow_null=True)
    device_name = serializers.CharField(source='device.name', read_only=True, allow_null=True)

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


class HelpFaqEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = HelpFaqEntry
        fields = ['id', 'title', 'content', 'display_order', 'updated_at']


class HelpFaqEntryWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    title = serializers.CharField(max_length=200)
    content = serializers.CharField(allow_blank=True)
