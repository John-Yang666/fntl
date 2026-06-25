from __future__ import annotations

from django.test import TestCase

from myapp.admin import EstimatedCountPaginator, LargeTableAdminMixin, MyDateRangePicker, RelayActionAdmin
from myapp.models import RelayAction


class LargeTableAdminTests(TestCase):
    def test_large_table_admin_uses_estimated_count_controls(self):
        self.assertIs(LargeTableAdminMixin.paginator, EstimatedCountPaginator)
        self.assertFalse(LargeTableAdminMixin.show_full_result_count)

    def test_relay_action_admin_avoids_unbounded_value_filters(self):
        self.assertEqual(RelayActionAdmin.list_filter, (("timestamp", MyDateRangePicker), "device"))

    def test_relay_action_has_device_timestamp_desc_index(self):
        index = next(
            (index for index in RelayAction._meta.indexes if index.name == "bt_relay_dev_ts_desc_idx"),
            None,
        )

        self.assertIsNotNone(index)
        self.assertEqual(index.fields, ["device", "-timestamp"])
