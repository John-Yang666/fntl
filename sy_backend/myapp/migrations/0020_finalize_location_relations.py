from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0019_location_tables_and_temp_relations"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="customuser",
            name="depots",
        ),
        migrations.RemoveField(
            model_name="device",
            name="depot",
        ),
        migrations.RemoveField(
            model_name="device",
            name="line",
        ),
        migrations.RenameField(
            model_name="customuser",
            old_name="depots_m2m",
            new_name="depots",
        ),
        migrations.RenameField(
            model_name="device",
            old_name="depot_ref",
            new_name="depot",
        ),
        migrations.RenameField(
            model_name="device",
            old_name="line_ref",
            new_name="line",
        ),
    ]
