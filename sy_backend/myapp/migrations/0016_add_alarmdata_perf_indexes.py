from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0015_delete_analogdata"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="alarmdata",
            index=models.Index(fields=["-timestamp_start"], name="sy_alarmdata_ts_desc_idx"),
        ),
        migrations.AddIndex(
            model_name="alarmdata",
            index=models.Index(fields=["is_confirmed", "-timestamp_start"], name="sy_alarmdata_conf_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="alarmdata",
            index=models.Index(fields=["device", "-timestamp_start"], name="sy_alarmdata_dev_ts_idx"),
        ),
    ]
