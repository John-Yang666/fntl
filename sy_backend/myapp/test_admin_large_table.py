from __future__ import annotations

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from myapp.admin import (
    EstimatedCountPaginator,
    LargeTableAdminMixin,
    MyDateRangePicker,
    RelayActionAdmin,
    RelayActionDeviceFilter,
)
from myapp.models import Depot, Device, Line, RelayAction, SYSTEM_ADMIN_GROUP_NAME


class LargeTableAdminTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.depot_a = Depot.objects.create(name="A车间", ordering=1)
        self.depot_b = Depot.objects.create(name="B车间", ordering=2)
        self.line = Line.objects.create(name="1号线", ordering=1)
        self.device_a = Device.objects.create(
            device_id=201,
            name="SY-A设备",
            depot=self.depot_a,
            line=self.line,
            ip_address="10.0.1.201",
        )
        Device.objects.create(
            device_id=202,
            name="SY-B设备",
            depot=self.depot_b,
            line=self.line,
            ip_address="10.0.1.202",
        )
        self.ops_user = user_model.objects.create_user("sy-admin-ops", "ops@example.com", "pw")
        system_admin_group, _created = Group.objects.get_or_create(name=SYSTEM_ADMIN_GROUP_NAME)
        self.ops_user.groups.add(system_admin_group)
        self.ops_user.depots.add(self.depot_a)

    def test_large_table_admin_uses_estimated_count_controls(self):
        self.assertIs(LargeTableAdminMixin.paginator, EstimatedCountPaginator)
        self.assertFalse(LargeTableAdminMixin.show_full_result_count)

    def test_relay_action_admin_avoids_unbounded_value_filters(self):
        self.assertEqual(RelayActionAdmin.list_filter, (("timestamp", MyDateRangePicker), RelayActionDeviceFilter))

    def test_relay_action_device_filter_uses_scoped_devices_not_action_records(self):
        request = RequestFactory().get("/")
        request.user = self.ops_user
        model_admin = RelayActionAdmin(RelayAction, AdminSite())
        filter_spec = RelayActionDeviceFilter(request, {}, RelayAction, model_admin)

        self.assertEqual(filter_spec.lookup_choices, [(201, str(self.device_a))])

    def test_relay_action_has_device_timestamp_desc_index(self):
        index = next(
            (index for index in RelayAction._meta.indexes if index.name == "sy_relay_dev_ts_desc_idx"),
            None,
        )

        self.assertIsNotNone(index)
        self.assertEqual(index.fields, ["device", "-timestamp"])
