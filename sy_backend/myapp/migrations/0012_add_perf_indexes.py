from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0011_device_direction1_cable_alarm_linkage_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="switchdata",
            index=models.Index(fields=["device", "timestamp"], name="sy_switch_dev_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="analogdata",
            index=models.Index(fields=["device", "timestamp"], name="sy_analog_dev_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="relayaction",
            index=models.Index(fields=["device", "timestamp"], name="sy_relay_dev_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="alarmdata",
            index=models.Index(fields=["device", "timestamp_start"], name="sy_alarmdata_dev_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="rawframelog",
            index=models.Index(fields=["device", "timestamp"], name="sy_rawframe_dev_ts_idx"),
        ),
    ]
