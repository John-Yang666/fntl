from django.db import migrations, models


def create_relayaction_device_timestamp_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS bt_relay_dev_ts_desc_idx
            ON myapp_relayaction (device_id, timestamp DESC)
            """
        )


def drop_relayaction_device_timestamp_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP INDEX CONCURRENTLY IF EXISTS bt_relay_dev_ts_desc_idx")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("myapp", "0012_cleanup_timestamp_indexes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    create_relayaction_device_timestamp_index,
                    drop_relayaction_device_timestamp_index,
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="relayaction",
                    index=models.Index(fields=["device", "-timestamp"], name="bt_relay_dev_ts_desc_idx"),
                ),
            ],
        ),
    ]
