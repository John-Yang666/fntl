# myproject/urls.py

from django.contrib import admin  # type: ignore
from django.urls import path, include  # type: ignore
from django.views.generic import RedirectView  # type: ignore

from rest_framework.routers import DefaultRouter  # type: ignore
from rest_framework_simplejwt.views import (  # type: ignore
    TokenObtainPairView,
    TokenRefreshView,
)

from myapp import views

# 标准资源操作：用于标准的 ViewSet，适合处理标准的模型操作。
router = DefaultRouter()
router.register(r"devices", views.DeviceViewSet)
router.register(r"switch-data", views.SwitchDataViewSet)
router.register(r"relay-actions", views.RelayActionViewSet)
router.register(r"user-operations", views.UserOperationViewSet)
router.register(r"alerts", views.AlarmDataViewSet)
router.register(r"uploaded-files", views.UploadedFileViewSet, basename="uploadedfile")

# 自定义操作：用于自定义的视图（View 或 APIView），适合处理特定的业务逻辑或自定义的 URL 格式。
urlpatterns = [
    # 根路径重定向到 /admin/
    path("", RedirectView.as_view(url="/admin/", permanent=True)),

    # Django admin 界面
    path("admin/", admin.site.urls),

    # DRF ViewSet 路由
    path("api/", include(router.urls)),

    # 状态类接口（缓存）
    path(
        "api/switch-status/<int:device_id>/",
        views.SwitchStatusView.as_view(),
        name="switch-status",
    ),

    # 设备列表（按线路分组，用于拓扑等）
    path(
        "api/devices-list/",
        views.DeviceListView.as_view(),
        name="device-list",
    ),

    # sy 串口命令发送入口（A1/A2/AA/BB 等）
    path(
        "api/sy/send-command/<int:device_id>/",
        views.SySendCommandView.as_view(),
        name="sy-send-command",
    ),

    # 拓扑状态
    path(
        "api/topology-status/<int:device_id>/",
        views.TopologyStatusView.as_view(),
        name="topology-status",
    ),
    path(
        "api/all-topology-status/",
        views.AllTopologyStatusView.as_view(),
        name="all_topology_status",
    ),

    # 告警相关
    path(
        "api/active-alarms/",
        views.ActiveAlarmListView.as_view(),
        name="active-alarms",
    ),
    path(
        "api/active-alarms/<int:device_id>/<int:alarm_code>/confirm/",
        views.ConfirmAlarmView.as_view(),
        name="confirm-alarm",
    ),

    # JWT 认证
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # 当前登录用户信息
    path("api/user/", views.UserDetailView.as_view(), name="user_detail"),

    # 文件下载
    path("api/download/<int:pk>/", views.download_file, name="file-download"),

    # sy 设备方向启用标志
    path(
        "api/device-flags/<int:device_id>/",
        views.DeviceFlagsView.as_view(),
        name="device-flags",
    ),

    # sy 设备详情（基础信息 + 最新 A1 & 最近 A2）
    path(
        "api/device-detail/<int:device_id>/",
        views.DeviceDetailView.as_view(),
        name="device-detail",
    ),

    # sy 设备开关量
    path("api/device_switch_data/<int:device_id>/", views.DeviceSwitchDataView.as_view(), name='device_switch_data'),
]

# 仅开发环境使用：静态文件/媒体文件
from django.conf import settings  # type: ignore
from django.conf.urls.static import static  # type: ignore

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
