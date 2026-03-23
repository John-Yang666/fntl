from django.db import migrations, models


def seed_help_faq_entries(apps, schema_editor):
    HelpFaqEntry = apps.get_model('myapp', 'HelpFaqEntry')
    if HelpFaqEntry.objects.exists():
        return

    HelpFaqEntry.objects.bulk_create([
        HelpFaqEntry(
            title='告警码含义',
            content=(
                '0 设备网管连接中断\n'
                '40 1方向电源板A状态\n'
                '41 1方向电源板B状态\n'
                '42 2方向电源板A状态\n'
                '43 2方向电源板B状态\n'
                '44 1方向CPU板A通信状态\n'
                '45 1方向CPU板B通信状态\n'
                '46 2方向CPU板A通信状态\n'
                '47 2方向CPU板B通信状态\n'
                '70 提醒：1方向QHJ状态与邻站不同\n'
                '71 1方向电缆状态\n'
                '72 提醒：1方向切换模式与邻站不同\n'
                '110 提醒：2方向QHJ状态与邻站不同\n'
                '111 2方向电缆状态\n'
                '112 提醒：2方向切换模式与邻站不同\n'
                '162 站间A通道或通信板故障（一方向A系）\n'
                '164 站间B通道或通信板故障（一方向A系）\n'
                '190 CPU板离线（一方向A系）\n'
                '252 站间A通道或通信板故障（一方向B系）\n'
                '254 站间B通道或通信板故障（一方向B系）\n'
                '280 CPU板离线（一方向B系）\n'
                '342 站间A通道或通信板故障（二方向A系）\n'
                '344 站间B通道或通信板故障（二方向A系）\n'
                '370 CPU板离线（二方向A系）\n'
                '432 站间A通道或通信板故障（二方向B系）\n'
                '434 站间B通道或通信板故障（二方向B系）\n'
                '460 CPU板离线（二方向B系）'
            ),
            display_order=1,
        ),
        HelpFaqEntry(
            title='修改系统设置',
            content=(
                '需要时，在厂家工程师指导下，在项目文件夹内打开文件：\n'
                '/BT_NMS/backend/myproject/settings.py\n'
                '或 BT_NMS 中复制后的 SY 编排文件。'
            ),
            display_order=2,
        ),
        HelpFaqEntry(
            title='其它',
            content='如果您在使用中有任何问题，欢迎联系我们，我们的专业团队将竭诚为您服务！',
            display_order=3,
        ),
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0005_device_direction1_enabled_device_direction2_enabled'),
    ]

    operations = [
        migrations.CreateModel(
            name='HelpFaqEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200, verbose_name='标题')),
                ('content', models.TextField(verbose_name='内容')),
                ('display_order', models.PositiveIntegerField(db_index=True, default=0, verbose_name='排序')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '帮助页常见问题',
                'verbose_name_plural': '帮助页常见问题',
                'ordering': ['display_order', 'id'],
            },
        ),
        migrations.RunPython(seed_help_faq_entries, migrations.RunPython.noop),
    ]
