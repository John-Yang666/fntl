from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("myapp", "0023_relayaction_device_timestamp_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserMonitoringPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "selection_mode",
                    models.CharField(
                        choices=[("all", "全部有权设备"), ("custom", "自定义设备")],
                        default="all",
                        max_length=10,
                        verbose_name="监控范围",
                    ),
                ),
                (
                    "monitored_devices",
                    models.ManyToManyField(blank=True, related_name="monitoring_preferences", to="myapp.device", verbose_name="监控设备"),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monitoring_preference",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="用户",
                    ),
                ),
            ],
            options={"verbose_name": "用户监控配置", "verbose_name_plural": "用户监控配置"},
        ),
        migrations.AddIndex(
            model_name="alarmdata",
            index=models.Index(fields=["device", "is_confirmed"], name="sy_alarmdata_dev_conf_idx"),
        ),
    ]
