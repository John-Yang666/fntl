from rest_framework import serializers
from myapp.models import Device, SwitchData, AlarmActive, AnalogData, RelayAction, AlarmData, UploadedFile

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

class AlarmDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlarmData
        fields = ['device_id', 'alarm_code', 'timestamp']

class UploadedFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = '__all__'