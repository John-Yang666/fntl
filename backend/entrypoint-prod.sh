#!/bin/bash
set -e

echo "==== [ENTRYPOINT] 等待 Redis 启动 ===="
/app/wait-for-it.sh redis:6379 --timeout=30 --strict -- echo "Redis is ready."

echo "==== [ENTRYPOINT] 等待 Postgres 启动 ===="
/app/wait-for-it.sh db:5432 --timeout=30 --strict -- echo "PostgreSQL is ready."

echo "==== [ENTRYPOINT] 当前工作目录: $(pwd)"
echo "==== [ENTRYPOINT] 当前目录内容: "
ls -la

load_file_secret() {
  local var_name="$1"
  local file_var_name="${var_name}_FILE"
  local file_path="${!file_var_name:-}"

  if [ -z "${file_path}" ]; then
    return 0
  fi
  if [ ! -r "${file_path}" ]; then
    echo "[错误] ${file_var_name} 指向不可读文件: ${file_path}" >&2
    exit 1
  fi

  export "${var_name}=$(cat "${file_path}")"
}

#echo "=== 迁移数据库（makemigrations）==="
#if ! python manage.py makemigrations; then
#  echo "[警告] makemigrations 执行失败，但继续执行 migrate"
#fi

echo "=== 执行 migrate（应用迁移）==="
python manage.py migrate

echo "==== [ENTRYPOINT] 收集静态文件 ===="
python manage.py collectstatic --noinput

load_file_secret DJANGO_SUPERUSER_PASSWORD

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] || [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  if [ -z "${DJANGO_SUPERUSER_USERNAME:-}" ] || [ -z "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    echo "[错误] DJANGO_SUPERUSER_USERNAME 和 DJANGO_SUPERUSER_PASSWORD 必须同时设置。" >&2
    exit 1
  fi
  case "${DJANGO_SUPERUSER_PASSWORD}" in
    admin|password|123456|12345678)
      echo "[错误] 拒绝使用默认/弱超级用户密码。" >&2
      exit 1
      ;;
  esac
  echo "==== [ENTRYPOINT] 自动创建超级用户（如果不存在） ===="
  python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ["DJANGO_SUPERUSER_USERNAME"]
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
PY
else
  echo "==== [ENTRYPOINT] 未设置 DJANGO_SUPERUSER_USERNAME/PASSWORD，跳过自动创建超级用户 ===="
fi

echo "==== [ENTRYPOINT] 启动 Uvicorn ASGI 服务器 ===="
exec uvicorn myproject.asgi:application --host 0.0.0.0 --port 8000
