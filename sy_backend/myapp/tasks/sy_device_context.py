from __future__ import annotations

from myapp.models import Device


DEVICE_CONTEXT_FIELDS = (
    "device_id",
    "name",
    "alarm_filters",
    "direction1_enabled",
    "direction2_enabled",
    "direction3_enabled",
    "direction1_neighbor_id",
    "direction1_neighbor_direction",
    "direction2_neighbor_id",
    "direction2_neighbor_direction",
    "direction1_cable_alarm_linkage",
    "direction2_cable_alarm_linkage",
)


def load_sy_device_context_cache() -> dict[int, dict]:
    rows = Device.objects.all().values(*DEVICE_CONTEXT_FIELDS)
    context_map: dict[int, dict] = {}
    for row in rows:
        context_map[row["device_id"]] = {
            "device_id": row["device_id"],
            "name": row["name"] or "",
            "alarm_filters": set(row["alarm_filters"] or []),
            "direction1_enabled": bool(row["direction1_enabled"]),
            "direction2_enabled": bool(row["direction2_enabled"]),
            "direction3_enabled": bool(row["direction3_enabled"]),
            "direction1_neighbor_id": row["direction1_neighbor_id"] or 0,
            "direction1_neighbor_direction": row["direction1_neighbor_direction"],
            "direction2_neighbor_id": row["direction2_neighbor_id"] or 0,
            "direction2_neighbor_direction": row["direction2_neighbor_direction"],
            "direction1_cable_alarm_linkage": bool(row["direction1_cable_alarm_linkage"]),
            "direction2_cable_alarm_linkage": bool(row["direction2_cable_alarm_linkage"]),
        }
    return context_map


def hash_sy_device_context_cache(context_map: dict[int, dict]) -> int:
    return hash(
        frozenset(
            (
                device_id,
                row["name"],
                tuple(sorted(row["alarm_filters"])),
                row["direction1_enabled"],
                row["direction2_enabled"],
                row["direction3_enabled"],
                row["direction1_neighbor_id"],
                row["direction1_neighbor_direction"],
                row["direction2_neighbor_id"],
                row["direction2_neighbor_direction"],
                row["direction1_cable_alarm_linkage"],
                row["direction2_cable_alarm_linkage"],
            )
            for device_id, row in context_map.items()
        )
    )

