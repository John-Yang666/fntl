import json

from rest_framework import serializers

from .models import Depot, Device, Line
from .ops_permissions import ensure_depot_allowed


def normalize_alarm_filters(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []

    normalized = []
    for item in value:
        if isinstance(item, bool):
            continue
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized


class OpsDepotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Depot
        fields = ["id", "name", "is_active", "ordering", "remark"]


class OpsLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Line
        fields = ["id", "name", "is_active", "ordering", "remark"]


class OpsDeviceSerializer(serializers.ModelSerializer):
    depot_id = serializers.PrimaryKeyRelatedField(source="depot", queryset=Depot.objects.all())
    line_id = serializers.PrimaryKeyRelatedField(source="line", queryset=Line.objects.all(), required=False, allow_null=True)
    depot_name = serializers.CharField(source="depot.name", read_only=True)
    line_name = serializers.CharField(source="line.name", read_only=True, allow_null=True)

    class Meta:
        model = Device
        fields = [
            "id",
            "device_id",
            "name",
            "depot_id",
            "depot_name",
            "line_id",
            "line_name",
            "ip_address",
            "x_coordinate",
            "y_coordinate",
            "direction1_neighbor_id",
            "direction1_neighbor_direction",
            "direction2_neighbor_id",
            "direction2_neighbor_direction",
            "direction1_enabled",
            "direction2_enabled",
            "alarm_filters",
            "remark",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["alarm_filters"] = normalize_alarm_filters(representation.get("alarm_filters"))
        return representation

    def validate(self, attrs):
        request = self.context["request"]
        depot = attrs.get("depot") or getattr(self.instance, "depot", None)
        ensure_depot_allowed(request.user, depot)

        device_id = attrs.get("device_id", getattr(self.instance, "device_id", None))
        ip_address = attrs.get("ip_address", getattr(self.instance, "ip_address", None))
        queryset = Device.objects.all()
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.filter(device_id=device_id).exists():
            raise serializers.ValidationError({"device_id": "设备ID已存在。"})
        if queryset.filter(ip_address=ip_address).exists():
            raise serializers.ValidationError({"ip_address": "IP地址已存在。"})

        if "alarm_filters" in attrs and (
            not isinstance(attrs["alarm_filters"], list)
            or any(not isinstance(item, int) for item in attrs["alarm_filters"])
        ):
            raise serializers.ValidationError({"alarm_filters": "过滤告警码必须是整数数组。"})

        for field in ("direction1_neighbor_id", "direction2_neighbor_id"):
            neighbor_id = attrs.get(field, getattr(self.instance, field, 0))
            if neighbor_id and not Device.objects.filter(device_id=neighbor_id).exists():
                raise serializers.ValidationError({field: "邻站ID不存在。"})
        return attrs
