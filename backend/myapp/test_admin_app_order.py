from __future__ import annotations

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase


class AdminAppOrderTests(TestCase):
    def test_myapp_models_start_with_business_record_order(self):
        user_model = get_user_model()
        user = user_model.objects.create_superuser("admin-order", "admin@example.com", "pw")
        request = RequestFactory().get("/admin/")
        request.user = user

        app = next(item for item in admin.site.get_app_list(request) if item["app_label"] == "myapp")
        model_names = [model["name"] for model in app["models"]]

        self.assertEqual(
            model_names[:6],
            ["历史告警", "继电器动作", "用户操作", "开关量数据", "电压电流数据", "设备信息"],
        )
