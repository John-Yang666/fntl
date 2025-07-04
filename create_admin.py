# create_admin.py
import os
from django.contrib.auth import get_user_model

username = os.getenv('DJANGO_SUPERUSER_USERNAME', 'admin')
email = os.getenv('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')
password = os.getenv('DJANGO_SUPERUSER_PASSWORD', 'admin123')

User = get_user_model()
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print("✔️ Superuser created.")
else:
    print("ℹ️ Superuser already exists.")