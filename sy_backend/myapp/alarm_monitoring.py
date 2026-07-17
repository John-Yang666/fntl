from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AlarmActive, AlarmData, Device, UserMonitoringPreference


SYSTEM = "sy"
ALARM_GROUP = "sy_alarm_state_updates"
REVISION_CACHE_KEY = "sy:alarm-state-revision"
logger = logging.getLogger(__name__)


def allowed_devices_for_user(user):
    queryset = Device.objects.all()
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    if user.is_superuser:
        return queryset
    depots = user.managed_depots_qs() if hasattr(user, "managed_depots_qs") else None
    if depots is not None and depots.exists():
        return queryset.filter(depot__in=depots)
    return queryset.none()


def monitored_devices_for_user(user):
    allowed = allowed_devices_for_user(user)
    try:
        preference = user.monitoring_preference
    except UserMonitoringPreference.DoesNotExist:
        return allowed
    if preference.selection_mode == UserMonitoringPreference.MODE_ALL:
        return allowed
    return allowed.filter(pk__in=preference.monitored_devices.values("pk"))


def monitored_device_ids_for_user(user) -> list[int]:
    return list(monitored_devices_for_user(user).order_by("device_id").values_list("device_id", flat=True))


def current_alarm_revision() -> int:
    return int(cache.get(REVISION_CACHE_KEY, 0) or 0)


def bump_alarm_revision() -> int:
    cache.add(REVISION_CACHE_KEY, 0, timeout=None)
    try:
        return int(cache.incr(REVISION_CACHE_KEY))
    except ValueError:
        cache.set(REVISION_CACHE_KEY, 1, timeout=None)
        return 1


def build_alarm_snapshot(user, *, revision: int | None = None) -> dict:
    device_ids = monitored_device_ids_for_user(user)
    current = AlarmActive.objects.filter(device_id__in=device_ids)
    current_unconfirmed = current.filter(is_confirmed=False)
    historical_unconfirmed = AlarmData.objects.filter(device_id__in=device_ids, is_confirmed=False)
    current_ids = [str(item) for item in current_unconfirmed.values_list("id", flat=True)]
    historical_ids = [str(item) for item in historical_unconfirmed.values_list("id", flat=True)]
    total_unconfirmed = len(current_ids) + len(historical_ids)
    return {
        "type": "alarm.snapshot",
        "system": SYSTEM,
        "revision": current_alarm_revision() if revision is None else int(revision),
        "current_count": current.count(),
        "current_unconfirmed_count": len(current_ids),
        "historical_unconfirmed_count": len(historical_ids),
        "total_unconfirmed_count": total_unconfirmed,
        "should_play": total_unconfirmed > 0,
        "audible_occurrence_ids": current_ids + historical_ids,
    }


def publish_alarm_state_changed(reason: str = "alarm.changed") -> int:
    revision = bump_alarm_revision()
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return revision
    try:
        async_to_sync(channel_layer.group_send)(
            ALARM_GROUP,
            {"type": "alarm.state.changed", "revision": revision, "reason": reason},
        )
    except Exception:
        logger.exception("Failed to publish alarm state change: %s", reason)
    return revision


class MonitoringPreferenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        allowed_ids = list(allowed_devices_for_user(request.user).order_by("device_id").values_list("device_id", flat=True))
        try:
            preference = request.user.monitoring_preference
        except UserMonitoringPreference.DoesNotExist:
            return Response({"selection_mode": UserMonitoringPreference.MODE_ALL, "device_ids": allowed_ids})
        return Response({"selection_mode": preference.selection_mode, "device_ids": monitored_device_ids_for_user(request.user)})

    def put(self, request):
        selection_mode = request.data.get("selection_mode")
        raw_ids = request.data.get("device_ids", [])
        if selection_mode not in {UserMonitoringPreference.MODE_ALL, UserMonitoringPreference.MODE_CUSTOM}:
            return Response({"detail": "selection_mode must be all or custom"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(raw_ids, list):
            return Response({"detail": "device_ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            requested_ids = {int(item) for item in raw_ids}
        except (TypeError, ValueError):
            return Response({"detail": "device_ids must contain integers"}, status=status.HTTP_400_BAD_REQUEST)

        allowed = allowed_devices_for_user(request.user)
        allowed_ids = set(allowed.values_list("device_id", flat=True))
        invalid_ids = sorted(requested_ids - allowed_ids)
        if invalid_ids:
            return Response({"detail": "devices outside user scope", "device_ids": invalid_ids}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            preference, _ = UserMonitoringPreference.objects.select_for_update().get_or_create(user=request.user)
            preference.selection_mode = selection_mode
            preference.save(update_fields=["selection_mode"])
            if selection_mode == UserMonitoringPreference.MODE_CUSTOM:
                preference.monitored_devices.set(allowed.filter(device_id__in=requested_ids))
            else:
                preference.monitored_devices.clear()
            transaction.on_commit(lambda: publish_alarm_state_changed("monitoring.changed"))

        return Response({"selection_mode": selection_mode, "device_ids": monitored_device_ids_for_user(request.user)})


class AlarmConfirmationsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        alarms = request.data.get("alarms", [])
        if not isinstance(alarms, list):
            return Response({"detail": "alarms must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        current_ids: list[str] = []
        historical_ids: list[str] = []
        for item in alarms:
            if not isinstance(item, dict) or not item.get("occurrence_id"):
                return Response({"detail": "each alarm requires source and occurrence_id"}, status=status.HTTP_400_BAD_REQUEST)
            source = item.get("source")
            if source == "current":
                current_ids.append(str(item["occurrence_id"]))
            elif source == "history":
                historical_ids.append(str(item["occurrence_id"]))
            else:
                return Response({"detail": "source must be current or history"}, status=status.HTTP_400_BAD_REQUEST)

        monitored_ids = monitored_device_ids_for_user(request.user)
        with transaction.atomic():
            current_count = AlarmActive.objects.filter(id__in=current_ids, device_id__in=monitored_ids, is_confirmed=False).update(is_confirmed=True)
            historical_count = AlarmData.objects.filter(id__in=historical_ids, device_id__in=monitored_ids, is_confirmed=False).update(is_confirmed=True)
            confirmed = current_count + historical_count
            if confirmed:
                transaction.on_commit(lambda: publish_alarm_state_changed("alarm.confirmed"))
        requested = len(current_ids) + len(historical_ids)
        return Response({"confirmed": confirmed, "skipped": max(requested - confirmed, 0)})
