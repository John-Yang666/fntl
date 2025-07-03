#!/bin/bash
set -e

echo "==== [ENTRYPOINT] 等待 Redis 启动 ===="
/app/wait-for-it.sh redis:6379 --timeout=30 --strict -- echo "Redis is ready."

echo "==== [ENTRYPOINT] 等待 Postgres 启动 ===="
/app/wait-for-it.sh db:5432 --timeout=30 --strict -- echo "PostgreSQL is ready."

echo "==== [ENTRYPOINT] 当前工作目录: $(pwd)"
echo "==== [ENTRYPOINT] 当前目录内容: "
ls -la

echo "=== 迁移数据库（makemigrations）==="
if ! python manage.py makemigrations; then
  echo "[警告] makemigrations 执行失败，但继续执行 migrate"
fi

echo "=== 执行 migrate（应用迁移）==="
python manage.py migrate

echo "==== [ENTRYPOINT] 收集静态文件 ===="
python manage.py collectstatic --noinput

echo "==== [ENTRYPOINT] 自动创建超级用户（如果不存在） ===="
echo "
from django.contrib.auth import get_user_model
User = get_user_model()
username = '${DJANGO_SUPERUSER_USERNAME}'
email = '${DJANGO_SUPERUSER_EMAIL}'
password = '${DJANGO_SUPERUSER_PASSWORD}'
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
" | python manage.py shell

#!/bin/bash
set -e

echo "==== [ENTRYPOINT] 等待 Redis 启动 ===="
/app/wait-for-it.sh redis:6379 --timeout=30 --strict -- echo "Redis is ready."

echo "==== [ENTRYPOINT] 等待 Postgres 启动 ===="
/app/wait-for-it.sh db:5432 --timeout=30 --strict -- echo "PostgreSQL is ready."

echo "==== [ENTRYPOINT] 当前工作目录: $(pwd)"
echo "==== [ENTRYPOINT] 当前目录内容: "
ls -la

echo "=== 迁移数据库（makemigrations）==="
if ! python manage.py makemigrations; then
  echo "[警告] makemigrations 执行失败，但继续执行 migrate"
fi

echo "=== 执行 migrate（应用迁移）==="
python manage.py migrate

echo "==== [ENTRYPOINT] 收集静态文件 ===="
python manage.py collectstatic --noinput

echo "==== [ENTRYPOINT] 自动创建超级用户（如果不存在） ===="
echo "
from django.contrib.auth import get_user_model
User = get_user_model()
username = '${DJANGO_SUPERUSER_USERNAME}'
email = '${DJANGO_SUPERUSER_EMAIL}'
password = '${DJANGO_SUPERUSER_PASSWORD}'
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
" | python manage.py shell

#echo "==== [ENTRYPOINT] 启动 Django 开发服务器 ===="
#exec python manage.py runserver 0.0.0.0:8000
echo "==== [ENTRYPOINT] 启动 Uvicorn ASGI 服务器 ===="
exec uvicorn myproject.asgi:application --host 0.0.0.0 --port 8000
