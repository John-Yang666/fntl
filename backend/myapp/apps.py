from django.apps import AppConfig
import os
import threading
from django.db.models.signals import post_migrate
from django.core.cache import cache

class MyappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myapp'
    verbose_name = "App数据"

    def ready(self):
        cache.clear()#启动时清空缓存的操作，避免错误的缓存信息无法清除。
        #if os.environ.get('RUN_MAIN') == 'true':  # 仅在运行 Django 开发服务器时启动

            # Start the UDP receiver thread
            #from .udp_receiver import udp_receiver
            #threading.Thread(target=udp_receiver, daemon=True).start()

            # Start the audio thread
            #from .audio_thread import audio_thread
            #threading.Thread(target=audio_thread, daemon=True).start()

            # Start the summarize_alarms thread
            #from .summarize_alarms_thread import summarize_alarms
            #threading.Thread(target=summarize_alarms, daemon=True).start()

            # Start the MQTT client
            #from .mqtt_client import start_mqtt
            #start_mqtt()

        post_migrate.connect(self.setup_periodic_tasks, sender=self)

    def setup_periodic_tasks(self, **kwargs):
        from django_celery_beat.models import PeriodicTask, CrontabSchedule
        import json

        # 创建或获取调度时间表，每天凌晨3点运行
        schedule, created = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='3',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        # 检查任务是否已经存在
        task_name = 'My Daily Task'
        if not PeriodicTask.objects.filter(name=task_name).exists():
            # 创建周期性任务
            PeriodicTask.objects.create(
                crontab=schedule,
                name=task_name,  # 任务名称
                task='myapp.tasks.my_daily_task.my_daily_task',
                args=json.dumps([3, 30, 30, 30, 30])  # 设置任务参数: switch_data, analog_data, alarm_data, relay_action, user_operation
            )
            print(f"Created periodic task: {task_name}")