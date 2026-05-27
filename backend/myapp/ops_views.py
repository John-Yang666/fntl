from django.http import HttpResponse
from django.utils import timezone
from rest_framework.pagination import PageNumberPagination
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import device_commands
from .device_import_export import commit_device_import, export_devices_csv, preview_device_import
from .models import Depot, Device, Line
from .ops_audit import log_device_operation, log_system_operation
from .ops_permissions import ensure_ops_access, scoped_depots_for_user, scoped_devices_for_user
from .ops_serializers import OpsDepotSerializer, OpsDeviceSerializer, OpsLineSerializer


class OpsPageNumberPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 10000


def dated_device_export_filename() -> str:
    return f"bt-devices-{timezone.localdate():%Y%m%d}.csv"


class OpsAccessMixin:
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        ensure_ops_access(request.user)


class OpsDepotViewSet(OpsAccessMixin, viewsets.ModelViewSet):
    serializer_class = OpsDepotSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return scoped_depots_for_user(self.request.user)

    def perform_create(self, serializer):
        depot = serializer.save()
        log_system_operation(user=self.request.user, function_code="ops_depot_create", operation=f"新增车间：{depot.name}")

    def perform_update(self, serializer):
        depot = serializer.save()
        log_system_operation(user=self.request.user, function_code="ops_depot_update", operation=f"修改车间：{depot.name}")


class OpsLineViewSet(OpsAccessMixin, viewsets.ModelViewSet):
    queryset = Line.objects.all().order_by("ordering", "name")
    serializer_class = OpsLineSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer):
        line = serializer.save()
        log_system_operation(user=self.request.user, function_code="ops_line_create", operation=f"新增线路：{line.name}")

    def perform_update(self, serializer):
        line = serializer.save()
        log_system_operation(user=self.request.user, function_code="ops_line_update", operation=f"修改线路：{line.name}")


class OpsDeviceViewSet(OpsAccessMixin, viewsets.ModelViewSet):
    serializer_class = OpsDeviceSerializer
    pagination_class = OpsPageNumberPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = scoped_devices_for_user(self.request.user)
        params = self.request.query_params
        if params.get("depot"):
            queryset = queryset.filter(depot_id=params["depot"])
        if params.get("line"):
            queryset = queryset.filter(line_id=params["line"])
        if params.get("device_id"):
            queryset = queryset.filter(device_id=params["device_id"])
        if params.get("name"):
            queryset = queryset.filter(name__icontains=params["name"])
        if params.get("ip_address"):
            queryset = queryset.filter(ip_address__icontains=params["ip_address"])
        if params.get("direction1_enabled") in {"true", "false"}:
            queryset = queryset.filter(direction1_enabled=params["direction1_enabled"] == "true")
        if params.get("direction2_enabled") in {"true", "false"}:
            queryset = queryset.filter(direction2_enabled=params["direction2_enabled"] == "true")
        return queryset.order_by("device_id")

    def perform_create(self, serializer):
        device = serializer.save()
        log_device_operation(user=self.request.user, device=device, function_code="ops_device_create", operation=f"新增设备：{device.name}")

    def perform_update(self, serializer):
        device = serializer.save()
        log_device_operation(user=self.request.user, device=device, function_code="ops_device_update", operation=f"修改设备：{device.name}")

    def perform_destroy(self, instance):
        log_system_operation(
            user=self.request.user,
            function_code="ops_device_delete",
            operation=f"删除设备：{instance.name}（{instance.device_id}）",
        )
        instance.delete()

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        requested_ids = [int(item) for item in request.data.get("device_ids", [])]
        scoped = self.get_queryset().filter(device_id__in=requested_ids)
        scoped_ids = set(scoped.values_list("device_id", flat=True))
        deleted = 0
        for device in list(scoped):
            device.delete()
            deleted += 1
        skipped = len(set(requested_ids) - scoped_ids)
        log_system_operation(
            user=request.user,
            function_code="ops_device_bulk_delete",
            operation=f"批量删除设备：成功 {deleted}，跳过 {skipped}",
        )
        return Response({"deleted": deleted, "skipped": skipped})

    @action(detail=False, methods=["post"], url_path="reconnect")
    def reconnect(self, request):
        requested_ids = [int(item) for item in request.data.get("device_ids", [])]
        devices = {device.device_id: device for device in self.get_queryset().filter(device_id__in=requested_ids)}
        results = []
        success = 0
        failed = 0
        skipped = 0
        for device_id in requested_ids:
            device = devices.get(device_id)
            if device is None:
                skipped += 1
                results.append({"device_id": device_id, "status": "skipped", "message": "设备不存在或无权操作"})
                continue
            try:
                device_commands.send_reconnect_packet_to_device(device)
                success += 1
                log_device_operation(
                    user=request.user,
                    device=device,
                    function_code="ops_device_reconnect",
                    operation=f"发送重连命令到 {device.ip_address}",
                )
                results.append({"device_id": device_id, "status": "success", "message": "已发送"})
            except Exception as exc:
                failed += 1
                results.append({"device_id": device_id, "status": "failed", "message": str(exc)})
        log_system_operation(
            user=request.user,
            function_code="ops_device_reconnect_batch",
            operation=f"批量重连设备：成功 {success}，失败 {failed}，跳过 {skipped}",
        )
        return Response({"total": len(requested_ids), "success": success, "failed": failed, "skipped": skipped, "results": results})

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        queryset = self.get_queryset()
        exported_count = queryset.count()
        content = export_devices_csv(queryset)
        log_system_operation(
            user=request.user,
            function_code="ops_device_export",
            operation=f"导出设备：{exported_count} 台",
        )
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{dated_device_export_filename()}"'
        return response


class OpsDeviceImportPreviewView(OpsAccessMixin, APIView):
    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            return Response({"detail": "缺少导入文件。"}, status=status.HTTP_400_BAD_REQUEST)
        result = preview_device_import(request.user, uploaded_file)
        summary = result["summary"]
        log_system_operation(
            user=request.user,
            function_code="ops_device_import_preview",
            operation=f"导入预检：新增 {summary['create']}，更新 {summary['update']}，错误 {summary['error']}",
        )
        return Response(result)


class OpsDeviceImportCommitView(OpsAccessMixin, APIView):
    def post(self, request):
        result = commit_device_import(request.user, request.data.get("rows", []))
        log_system_operation(
            user=request.user,
            function_code="ops_device_import_commit",
            operation=f"导入提交：新增 {result['created']}，更新 {result['updated']}",
        )
        return Response(result)
