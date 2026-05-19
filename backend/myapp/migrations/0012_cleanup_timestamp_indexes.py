from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0011_finalize_location_relations"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="switchdata",
            index=models.Index(fields=["timestamp"], name="bt_switch_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="analogdata",
            index=models.Index(fields=["timestamp"], name="bt_analog_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="relayaction",
            index=models.Index(fields=["timestamp"], name="bt_relay_ts_idx"),
        ),
        migrations.AddIndex(
            model_name="useroperation",
            index=models.Index(fields=["timestamp"], name="bt_userop_ts_idx"),
        ),
    ]
