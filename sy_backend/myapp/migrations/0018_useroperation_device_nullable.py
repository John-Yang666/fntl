from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0017_runtimeconfig"),
    ]

    operations = [
        migrations.AlterField(
            model_name="useroperation",
            name="device",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to_field="device_id",
                to="myapp.device",
                verbose_name="设备",
            ),
        ),
    ]
