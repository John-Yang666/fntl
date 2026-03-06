from django.contrib import admin # type: ignore
from django.urls import path, include # type: ignore
from django.views.generic import RedirectView  # 导入 RedirectView
from rest_framework.routers import DefaultRouter # type: ignore
from myapp import views
from rest_framework_simplejwt.views import ( # type: ignore
    TokenObtainPairView,
    TokenRefreshView,
)

# 标准资源操作：用于标准的 ViewSet，适合处理标准的模型操作。
router = DefaultRouter()
router.register(r'devices', views.DeviceViewSet)
router.register(r'switch-data', views.SwitchDataViewSet)
router.register(r'analog-data', views.AnalogDataViewSet)
router.register(r'relay-actions', views.RelayActionViewSet)
router.register(r'alerts', views.AlarmDataViewSet)
router.register(r'uploaded-files', views.UploadedFileViewSet, basename='uploadedfile')

# 自定义操作：用于自定义的视图（View 或 APIView），适合处理特定的业务逻辑或自定义的 URL 格式。
urlpatterns = [
    path('', RedirectView.as_view(url='/admin/', permanent=True)),  # 将根路径重定向到 /admin/
    path('admin/', admin.site.urls),  # 启用 admin 界面
    path('api/', include(router.urls)),
    path('api/switch-status/<int:device_id>/', views.SwitchStatusView.as_view(), name='switch-status'),
    path('api/analog-status/<int:device_id>/', views.AnalogStatusView.as_view(), name='analog-status'),
    path('api/devices-list/', views.DeviceListView.as_view(), name='device-list'),
    path('api/send-command/<int:device_id>/', views.SendCommandView.as_view(), name='send-command'),
    path('api/topology-status/<int:device_id>/', views.TopologyStatusView.as_view(), name='topology-status'),  # 拓扑状态视图
    path('api/all-topology-status/', views.AllTopologyStatusView.as_view(), name='all_topology_status'),  # 所有拓扑状态视图
    path('api/active-alarms/', views.ActiveAlarmListView.as_view()),
    path('api/active-alarms/<int:device_id>/<int:alarm_code>/confirm/', views.ConfirmAlarmView.as_view()),
    #path('api/alerts-amount/', views.AlertsAmountView.as_view()),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/user/', views.UserDetailView.as_view(), name='user_detail'),
    path('api/download/<int:pk>/', views.download_file, name='file-download'),
    path('api/device-flags/<int:device_id>/', views.DeviceFlagsView.as_view(), name='device-flags'),
    # path('reset_periodic_tasks/', views.reset_periodic_tasks, name='reset_periodic_tasks'),#注意：确保执行完该操作后立即删除此视图和 URL 配置，以防止未授权的访问。
]

# 👇👇👇 添加在文件最后（只在开发环境使用）
from django.conf import settings
from django.conf.urls.static import static

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
