# BT Ops Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-phase BT operations console so authorized users can manage BT depots, lines, devices, imports/exports, and reconnect commands from the frontend.

**Architecture:** Add dedicated DRF ops APIs under `/api/ops/*`, backed by small service modules for permissions, audit logging, reconnect command sending, and device import/export. Add a Vue `/ops` route that talks only to the BT backend and provides tabbed management for devices, depots, lines, and import/export results while preserving the existing backend Admin links.

**Tech Stack:** Django 5, Django REST Framework, django-filter, tablib/django-import-export dependencies, Vue 3, TypeScript, Element Plus, Pinia, Vite.

---

## File Structure

- Create `backend/myapp/ops_permissions.py`: central permission checks and scoped querysets for ops APIs.
- Create `backend/myapp/ops_audit.py`: user operation logging helpers for system-level and device-level actions.
- Create `backend/myapp/device_commands.py`: reconnect command packet building and Redis Stream sending, extracted from Admin behavior.
- Create `backend/myapp/device_import_export.py`: CSV/XLSX parsing, preview validation, commit, and export payload generation.
- Create `backend/myapp/ops_serializers.py`: serializers for depots, lines, ops devices, import preview, and bulk actions.
- Create `backend/myapp/ops_views.py`: ViewSets/APIViews for `/api/ops/*`.
- Modify `backend/myproject/urls.py`: register ops routes.
- Modify `backend/myapp/admin.py`: reuse reconnect command helper while preserving current Admin behavior.
- Create `backend/myapp/test_ops_api.py`: API and service coverage for permissions, CRUD, import preview/commit, export, and reconnect.
- Create `frontend/src/views/OpsConsoleView.vue`: BT-only operations console.
- Modify `frontend/src/router/index.ts`: add `/ops` route guarded by authentication and ops permission.
- Modify `frontend/src/components/HeaderComponent.vue`: add “运维管理” tab for superusers and System Admin users.
- Modify `frontend/src/stores/userStore.ts`: add `canAccessOps` getter.

## Task 1: Backend Permission and Audit Helpers

**Files:**
- Create: `backend/myapp/ops_permissions.py`
- Create: `backend/myapp/ops_audit.py`
- Test: `backend/myapp/test_ops_api.py`

- [ ] **Step 1: Write failing permission tests**

Add `OpsPermissionTests` to `backend/myapp/test_ops_api.py`:

```python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from myapp.models import Depot, Device, Line, SYSTEM_ADMIN_GROUP_NAME, UserOperation
from myapp.ops_permissions import (
    ensure_ops_access,
    scoped_depots_for_user,
    scoped_devices_for_user,
)
from myapp.ops_audit import log_device_operation, log_system_operation


class OpsPermissionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.depot_a = Depot.objects.create(name="A车间", ordering=1)
        self.depot_b = Depot.objects.create(name="B车间", ordering=2)
        self.line = Line.objects.create(name="1号线")
        self.device_a = Device.objects.create(
            device_id=101,
            name="A设备",
            depot=self.depot_a,
            line=self.line,
            ip_address="10.0.0.101",
        )
        self.device_b = Device.objects.create(
            device_id=102,
            name="B设备",
            depot=self.depot_b,
            line=self.line,
            ip_address="10.0.0.102",
        )
        self.superuser = user_model.objects.create_superuser("root", "root@example.com", "pw")
        self.ops_user = user_model.objects.create_user("ops", "ops@example.com", "pw")
        self.regular_user = user_model.objects.create_user("regular", "regular@example.com", "pw")
        self.ops_group = Group.objects.get(name=SYSTEM_ADMIN_GROUP_NAME)
        self.ops_user.groups.add(self.ops_group)
        self.ops_user.depots.add(self.depot_a)

    def test_superuser_can_access_all_ops_data(self):
        ensure_ops_access(self.superuser)
        self.assertEqual(set(scoped_depots_for_user(self.superuser)), {self.depot_a, self.depot_b})
        self.assertEqual(set(scoped_devices_for_user(self.superuser)), {self.device_a, self.device_b})

    def test_system_admin_is_scoped_to_assigned_depots(self):
        ensure_ops_access(self.ops_user)
        self.assertEqual(list(scoped_depots_for_user(self.ops_user)), [self.depot_a])
        self.assertEqual(list(scoped_devices_for_user(self.ops_user)), [self.device_a])

    def test_regular_user_cannot_access_ops(self):
        with self.assertRaises(PermissionDenied):
            ensure_ops_access(self.regular_user)

    def test_audit_helpers_create_user_operations(self):
        log_system_operation(user=self.ops_user, function_code="ops_line_update", operation="修改线路：1号线")
        log_device_operation(
            user=self.ops_user,
            device=self.device_a,
            function_code="ops_device_update",
            operation="修改设备：A设备",
        )

        operations = list(UserOperation.objects.order_by("timestamp"))
        self.assertEqual(operations[0].device, None)
        self.assertEqual(operations[0].username, "ops")
        self.assertEqual(operations[0].function_code, "ops_line_update")
        self.assertEqual(operations[1].device, self.device_a)
        self.assertEqual(operations[1].username, "ops")
        self.assertEqual(operations[1].function_code, "ops_device_update")
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend && python manage.py test myapp.test_ops_api.OpsPermissionTests -v 2`

Expected: import failure for `myapp.ops_permissions`.

- [ ] **Step 3: Implement permission and audit helpers**

Create `backend/myapp/ops_permissions.py`:

```python
from django.contrib.auth.models import Group
from rest_framework.exceptions import PermissionDenied

from .models import Depot, Device, SYSTEM_ADMIN_GROUP_NAME


def user_has_ops_access(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
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
```

Create `backend/myapp/ops_audit.py`:

```python
from .models import UserOperation


def _username(user) -> str:
    return getattr(user, "username", "") or ""


def log_system_operation(*, user, function_code: str, operation: str) -> UserOperation:
    return UserOperation.objects.create(
        device=None,
        function_code=function_code,
        operation=operation,
        username=_username(user),
    )


def log_device_operation(*, user, device, function_code: str, operation: str) -> UserOperation:
    return UserOperation.objects.create(
        device=device,
        function_code=function_code,
        operation=operation,
        username=_username(user),
    )
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `cd backend && python manage.py test myapp.test_ops_api.OpsPermissionTests -v 2`

Expected: all tests in `OpsPermissionTests` pass.

## Task 2: Depot and Line Ops APIs

**Files:**
- Create: `backend/myapp/ops_serializers.py`
- Create: `backend/myapp/ops_views.py`
- Modify: `backend/myproject/urls.py`
- Test: `backend/myapp/test_ops_api.py`

- [ ] **Step 1: Write failing API tests**

Add `OpsDepotLineApiTests` to `backend/myapp/test_ops_api.py`:

```python
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class OpsDepotLineApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.depot_a = Depot.objects.create(name="A车间", ordering=1)
        self.depot_b = Depot.objects.create(name="B车间", ordering=2)
        self.line = Line.objects.create(name="1号线", ordering=1)
        self.superuser = user_model.objects.create_superuser("root-api", "root-api@example.com", "pw")
        self.ops_user = user_model.objects.create_user("ops-api", "ops-api@example.com", "pw")
        self.regular_user = user_model.objects.create_user("regular-api", "regular-api@example.com", "pw")
        self.ops_user.groups.add(Group.objects.get(name=SYSTEM_ADMIN_GROUP_NAME))
        self.ops_user.depots.add(self.depot_a)

    def test_regular_user_cannot_list_depots(self):
        self.client.force_authenticate(self.regular_user)
        response = self.client.get(reverse("ops-depot-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_system_admin_lists_only_assigned_depots(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.get(reverse("ops-depot-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["name"] for item in response.data["results"]], ["A车间"])

    def test_system_admin_can_update_assigned_depot(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.patch(
            reverse("ops-depot-detail", args=[self.depot_a.id]),
            {"remark": "已维护", "ordering": 5},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.depot_a.refresh_from_db()
        self.assertEqual(self.depot_a.remark, "已维护")
        self.assertEqual(self.depot_a.ordering, 5)
        self.assertTrue(UserOperation.objects.filter(function_code="ops_depot_update").exists())

    def test_system_admin_cannot_update_unassigned_depot(self):
        self.client.force_authenticate(self.ops_user)
        response = self.client.patch(
            reverse("ops-depot-detail", args=[self.depot_b.id]),
            {"remark": "越权"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_superuser_can_create_line(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            reverse("ops-line-list"),
            {"name": "2号线", "is_active": True, "ordering": 2, "remark": "新线"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Line.objects.filter(name="2号线").exists())
        self.assertTrue(UserOperation.objects.filter(function_code="ops_line_create").exists())
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend && python manage.py test myapp.test_ops_api.OpsDepotLineApiTests -v 2`

Expected: URL reverse failure for `ops-depot-list`.

- [ ] **Step 3: Implement serializers, views, and routes**

Create serializers and viewsets that:
- Use `ensure_ops_access`.
- Scope depot queryset via `scoped_depots_for_user`.
- Allow line queryset for any ops user.
- Log create/update actions with `ops_audit`.

Register routes in `backend/myproject/urls.py` with:

```python
ops_router = DefaultRouter()
ops_router.register(r"depots", views.OpsDepotViewSet, basename="ops-depot")
ops_router.register(r"lines", views.OpsLineViewSet, basename="ops-line")
path("api/ops/", include(ops_router.urls)),
```

If keeping ops views in `myapp.ops_views`, import them as `ops_views` instead of mixing into `myapp.views`.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `cd backend && python manage.py test myapp.test_ops_api.OpsDepotLineApiTests -v 2`

Expected: all tests pass.

## Task 3: Device CRUD and Reconnect APIs

**Files:**
- Create: `backend/myapp/device_commands.py`
- Modify: `backend/myapp/ops_serializers.py`
- Modify: `backend/myapp/ops_views.py`
- Modify: `backend/myapp/admin.py`
- Test: `backend/myapp/test_ops_api.py`

- [ ] **Step 1: Write failing device tests**

Add tests for:
- System Admin listing only assigned depot devices.
- Creating a device in an assigned depot.
- Rejecting creation in an unassigned depot.
- Updating device fields.
- Deleting a scoped device.
- Reconnect returning per-device success/failure while skipping unauthorized IDs.

Patch `device_commands.send_reconnect_packet_to_device` in reconnect tests so no Redis connection is required.

- [ ] **Step 2: Run device tests and verify RED**

Run: `cd backend && python manage.py test myapp.test_ops_api.OpsDeviceApiTests -v 2`

Expected: URL reverse failure for `ops-device-list`.

- [ ] **Step 3: Implement device serializer and views**

Implement an ops device serializer with writable `depot_id` and `line_id`, plus read-only `depot_name` and `line_name`. Validate:
- `device_id` uniqueness.
- `ip_address` uniqueness.
- depot exists and is allowed.
- line exists when provided.
- neighbor IDs exist or are blank/zero.
- `alarm_filters` is a list of integers.

Add viewset routes:

```python
ops_router.register(r"devices", ops_views.OpsDeviceViewSet, basename="ops-device")
```

Add custom actions:

```text
POST /api/ops/devices/bulk-delete/
POST /api/ops/devices/reconnect/
```

- [ ] **Step 4: Run device tests and verify GREEN**

Run: `cd backend && python manage.py test myapp.test_ops_api.OpsDeviceApiTests -v 2`

Expected: all device API tests pass.

## Task 4: Device Import and Export APIs

**Files:**
- Create: `backend/myapp/device_import_export.py`
- Modify: `backend/myapp/ops_views.py`
- Test: `backend/myapp/test_ops_api.py`

- [ ] **Step 1: Write failing import/export tests**

Add tests for:
- Export only includes scoped devices and expected Chinese column names.
- Import preview reports creates, updates, and row-level errors without writing.
- Import commit writes only valid preview rows.
- Import rejects unassigned depot.

Use CSV input first; keep XLSX parsing as supported behavior through `tablib.Dataset().load(...)` with format detection.

- [ ] **Step 2: Run import/export tests and verify RED**

Run: `cd backend && python manage.py test myapp.test_ops_api.OpsDeviceImportExportTests -v 2`

Expected: URL reverse failure or missing helper failure.

- [ ] **Step 3: Implement import/export service and views**

Implement:
- `export_devices_csv(user, queryset)` returning CSV bytes.
- `preview_device_import(user, uploaded_file)` returning counts, valid rows, and errors.
- `commit_device_import(user, rows)` creating/updating devices inside a transaction.

Add views:

```text
GET  /api/ops/devices/export/
POST /api/ops/devices/import/preview/
POST /api/ops/devices/import/commit/
```

- [ ] **Step 4: Run import/export tests and verify GREEN**

Run: `cd backend && python manage.py test myapp.test_ops_api.OpsDeviceImportExportTests -v 2`

Expected: all import/export tests pass.

## Task 5: Frontend Ops Route, Navigation, and Layout

**Files:**
- Create: `frontend/src/views/OpsConsoleView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/HeaderComponent.vue`
- Modify: `frontend/src/stores/userStore.ts`

- [ ] **Step 1: Add frontend route and access getter**

Add `canAccessOps` getter:

```ts
canAccessOps: (state: UserState): boolean =>
  SYSTEMS.some((system) =>
    !!state.auth[system].user?.is_superuser ||
    !!state.auth[system].user?.groups.includes('System Admin'),
  ),
```

Add route:

```ts
{
  path: '/ops',
  name: 'opsConsole',
  component: () => import('../views/OpsConsoleView.vue'),
  meta: { requiresAuth: true, requiresOpsAccess: true }
}
```

Update route guard to redirect users without ops access to `/main`.

- [ ] **Step 2: Implement `OpsConsoleView.vue` skeleton**

Build a BT-only Element Plus page with tabs/side navigation:
- 设备信息
- 车间管理
- 线路管理
- 导入导出
- 操作结果

Wire load functions to `/ops/depots/`, `/ops/lines/`, and `/ops/devices/`.

- [ ] **Step 3: Update header navigation**

Show “运维管理” tab when `userStore.canAccessOps` is true and route to `/ops`.

- [ ] **Step 4: Verify frontend build**

Run: `cd frontend && npm run type-check`

Expected: TypeScript check passes.

## Task 6: Frontend CRUD, Bulk Actions, Import, and Export

**Files:**
- Modify: `frontend/src/views/OpsConsoleView.vue`

- [ ] **Step 1: Implement depot and line tables**

Support add/edit dialogs, active switch, ordering, and remark fields.

- [ ] **Step 2: Implement device table and form**

Support filters, pagination, create, edit, copy create, delete, and bulk delete. Use `depot_id`, `line_id`, and neighbor device selectors.

- [ ] **Step 3: Implement reconnect actions**

Support single and bulk reconnect with confirmation and result details.

- [ ] **Step 4: Implement import/export panel**

Support device CSV/XLSX upload preview, error table, commit, and export with current filters.

- [ ] **Step 5: Verify frontend build**

Run: `cd frontend && npm run build`

Expected: type-check and Vite build pass.

## Task 7: Full Verification

**Files:**
- All modified backend and frontend files.

- [ ] **Step 1: Run backend ops tests**

Run: `cd backend && python manage.py test myapp.test_ops_api -v 2`

Expected: all ops tests pass.

- [ ] **Step 2: Run existing focused backend tests**

Run: `cd backend && python manage.py test myapp.test_runtime_config myapp.tests -v 2`

Expected: tests pass or only fail due unavailable external database/services, which must be reported exactly.

- [ ] **Step 3: Run frontend production build**

Run: `cd frontend && npm run build`

Expected: build exits 0.

- [ ] **Step 4: Start frontend if needed and inspect `/ops`**

Run: `cd frontend && npm run dev -- --host 127.0.0.1`

Open the local URL and verify:
- Header shows 运维管理 for an ops-capable login.
- `/ops` renders without layout overlap.
- Existing “打开后端界面” links remain in Records.

Stop the dev server before final response.
