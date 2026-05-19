from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0021_relayaction_source"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="rawframelog",
            index=models.Index(fields=["timestamp"], name="sy_rawframe_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="switchdata",
            index=models.Index(fields=["timestamp"], name="sy_switch_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="changebitevent",
            index=models.Index(fields=["timestamp"], name="sy_changebit_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="relayaction",
            index=models.Index(fields=["timestamp"], name="sy_relay_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="useroperation",
            index=models.Index(fields=["timestamp"], name="sy_userop_ts_idx"),
        ),
    ]
