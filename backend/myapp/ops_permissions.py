from rest_framework.exceptions import PermissionDenied

from .models import Depot, Device, SYSTEM_ADMIN_GROUP_NAME


def user_has_ops_access(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    if user.is_staff:
        return True
    return user.groups.filter(name=SYSTEM_ADMIN_GROUP_NAME).exists()


def ensure_ops_access(user) -> None:
    if not user_has_ops_access(user):
        raise PermissionDenied("无权访问运维管理。")


def scoped_depots_for_user(user):
    ensure_ops_access(user)
    queryset = Depot.objects.all().order_by("ordering", "name")
    if user.is_superuser:
        return queryset
    return queryset.filter(id__in=user.depots.values("id"))


def scoped_devices_for_user(user):
    ensure_ops_access(user)
    queryset = Device.objects.select_related("depot", "line").all().order_by("device_id")
    if user.is_superuser:
        return queryset
    return queryset.filter(depot__in=user.depots.all())


def ensure_depot_allowed(user, depot) -> None:
    ensure_ops_access(user)
    if depot is None:
        raise PermissionDenied("设备必须选择车间。")
    if user.is_superuser:
        return
    if not user.depots.filter(pk=depot.pk).exists():
        raise PermissionDenied("无权管理该车间。")


def ensure_device_allowed(user, device) -> None:
    ensure_ops_access(user)
    ensure_depot_allowed(user, device.depot)
