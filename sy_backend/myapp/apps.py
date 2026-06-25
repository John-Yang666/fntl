from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.core.cache import cache

class MyappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'myapp'
    verbose_name = "App数据"

    def ready(self):
        cache.clear()#启动时清空缓存的操作，避免错误的缓存信息无法清除。
        post_migrate.connect(self.setup_periodic_tasks, sender=self)

    def setup_periodic_tasks(self, **kwargs):
        from django.apps import apps

        if not apps.is_installed("django_celery_beat"):
            return

        try:
            from django_celery_beat.models import PeriodicTask, CrontabSchedule
        except ModuleNotFoundError:
            return
        import json
        from myapp.runtime_config import CLEANUP_DEFAULT_SCHEDULE_TIME, CLEANUP_TASK_NAME, build_default_cleanup_task_args

        # 创建或获取调度时间表，每天凌晨3点运行
        schedule, created = CrontabSchedule.objects.get_or_create(
            minute=CLEANUP_DEFAULT_SCHEDULE_TIME.split(':', 1)[1],
            hour=str(int(CLEANUP_DEFAULT_SCHEDULE_TIME.split(':', 1)[0])),
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        # 检查任务是否已经存在
        task_name = CLEANUP_TASK_NAME
        if not PeriodicTask.objects.filter(name=task_name).exists():
            # 创建周期性任务
            PeriodicTask.objects.create(
                crontab=schedule,
                name=task_name,  # 任务名称
                task='myapp.tasks.my_daily_task.my_daily_task',
                args=json.dumps(build_default_cleanup_task_args())
            )
            print(f"Created periodic task: {task_name}")
