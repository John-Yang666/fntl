from django.db import migrations, models
import django.db.models.deletion


def populate_location_relations(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Device = apps.get_model("myapp", "Device")
    CustomUser = apps.get_model("myapp", "CustomUser")
    Depot = apps.get_model("myapp", "Depot")
    Line = apps.get_model("myapp", "Line")

    depot_ids_by_name = {}
    line_ids_by_name = {}

    def get_depot_id(raw_name):
        name = str(raw_name or "").strip()
        if not name:
            return None
        depot_id = depot_ids_by_name.get(name)
        if depot_id is None:
            depot, _ = Depot.objects.using(db_alias).get_or_create(name=name)
            depot_id = depot.pk
            depot_ids_by_name[name] = depot_id
        return depot_id

    def get_line_id(raw_name):
        name = str(raw_name or "").strip()
        if not name:
            return None
        line_id = line_ids_by_name.get(name)
        if line_id is None:
            line, _ = Line.objects.using(db_alias).get_or_create(name=name)
            line_id = line.pk
            line_ids_by_name[name] = line_id
        return line_id

    for device in Device.objects.using(db_alias).all().iterator():
        depot_id = get_depot_id(getattr(device, "depot", None))
        line_id = get_line_id(getattr(device, "line", None))
        update_fields = []
        if depot_id is not None:
            device.depot_ref_id = depot_id
            update_fields.append("depot_ref")
        if line_id is not None:
            device.line_ref_id = line_id
            update_fields.append("line_ref")
        if update_fields:
            device.save(update_fields=update_fields)

    for user in CustomUser.objects.using(db_alias).all().iterator():
        raw_depots = getattr(user, "depots", None)
        if not isinstance(raw_depots, list):
            continue
        depot_ids = []
        for raw_name in raw_depots:
            depot_id = get_depot_id(raw_name)
            if depot_id is not None:
                depot_ids.append(depot_id)
        if depot_ids:
            user.depots_m2m.add(*depot_ids)


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0018_useroperation_device_nullable"),
    ]

    operations = [
        migrations.CreateModel(
            name="Depot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True, verbose_name="车间名称")),
                ("is_active", models.BooleanField(default=True, verbose_name="启用")),
                ("remark", models.CharField(blank=True, default="", max_length=200, verbose_name="备注")),
                ("ordering", models.PositiveIntegerField(default=0, verbose_name="排序")),
            ],
            options={
                "verbose_name": "车间",
                "verbose_name_plural": "车间",
                "ordering": ["ordering", "name"],
            },
        ),
        migrations.CreateModel(
            name="Line",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True, verbose_name="线路名称")),
                ("is_active", models.BooleanField(default=True, verbose_name="启用")),
                ("remark", models.CharField(blank=True, default="", max_length=200, verbose_name="备注")),
                ("ordering", models.PositiveIntegerField(default=0, verbose_name="排序")),
            ],
            options={
                "verbose_name": "线路",
                "verbose_name_plural": "线路",
                "ordering": ["ordering", "name"],
            },
        ),
        migrations.AddField(
            model_name="device",
            name="depot_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="myapp.depot",
                verbose_name="车间",
            ),
        ),
        migrations.AddField(
            model_name="device",
            name="line_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="myapp.line",
                verbose_name="线路",
            ),
        ),
        migrations.AddField(
            model_name="customuser",
            name="depots_m2m",
            field=models.ManyToManyField(blank=True, to="myapp.depot", verbose_name="可管理车间"),
        ),
        migrations.RunPython(populate_location_relations, migrations.RunPython.noop),
    ]
