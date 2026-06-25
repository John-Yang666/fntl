# Django 5.2 LTS And Python 3.14 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the BT/SY Django backends from Django 5.0.6 on Python 3.12 toward Django 5.2 LTS, then verify and switch Docker runtime to Python 3.14.

**Architecture:** Keep the upgrade split into two validation gates. First upgrade Python dependencies while Docker still runs Python 3.12, then switch Docker base images and compose image tags to Python 3.14 only after backend tests pass.

**Tech Stack:** Django 5.2 LTS, Django REST Framework, Celery, Channels, PostgreSQL, Redis, Docker Compose, Python 3.12/3.14.

---

### Task 1: Dependency Upgrade On Python 3.12

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements.lock.txt`
- Modify: `sy_backend/requirements.txt`
- Modify: `sy_backend/requirements.lock.txt`

- [ ] **Step 1: Update direct dependency pins**

Set both backend requirement files to current compatible versions:

```text
celery==5.6.3
channels==4.3.2
channels-redis==4.3.0
django==5.2.15
django-celery-beat==2.9.0
django-celery-results==2.6.0
django-cors-headers==4.9.0
django-filter==25.2
django-import-export==4.4.1
django-redis==7.0.0
djangorestframework==3.17.1
djangorestframework-simplejwt==5.5.1
gevent==26.5.0
greenlet==3.5.2
psycopg2==2.9.12
uvicorn[standard]==0.49.0
```

- [ ] **Step 2: Regenerate lock files from a clean Python 3.12 install**

Run one clean install for each backend and freeze resolved packages:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app python:3.12 bash -lc 'python -m pip install --upgrade pip && python -m pip install -r requirements.txt && python -m pip freeze'
docker run --rm -v "$PWD/sy_backend:/app" -w /app python:3.12 bash -lc 'python -m pip install --upgrade pip && python -m pip install -r requirements.txt && python -m pip freeze'
```

- [ ] **Step 3: Verify Django imports and system checks under Python 3.12 image**

Run:

```bash
docker build -t my_django:v5.0.6 backend
docker compose -f docker-compose.yml run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py check
docker compose -f docker-compose-sy.yml run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py check
```

Expected: all commands exit `0`.

- [ ] **Step 4: Run backend tests under Python 3.12 image**

Run:

```bash
docker compose -f docker-compose.yml run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py test myapp -v 1
docker compose -f docker-compose-sy.yml run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py test myapp -v 1
```

Expected: BT and SY backend test suites pass.

### Task 2: Python 3.14 Runtime Switch

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `backend/Dockerfile.prod`
- Modify: `backend/Dockerfile_summarize_alarms`
- Modify: `backend/Dockerfile_udp_id_receiver`
- Modify: `sy_backend/Dockerfile`
- Modify: `sy_backend/Dockerfile.prod`
- Modify: `sy_backend/Dockerfile_summarize_alarms`
- Modify: `sy_backend/Dockerfile_udp_id_receiver`
- Modify: `docker-compose.yml`
- Modify: `docker-compose-sy.yml`

- [ ] **Step 1: Update Docker base images**

Change general backend images from:

```dockerfile
FROM python:3.12
```

to:

```dockerfile
FROM python:3.14
```

Change slim utility images from:

```dockerfile
FROM python:3.12-slim
```

to:

```dockerfile
FROM python:3.14-slim
```

- [ ] **Step 2: Update compose image tags**

Change backend service image tags from:

```yaml
image: my_django:v5.0.6
```

to:

```yaml
image: my_django:v5.2.15-py3.14
```

- [ ] **Step 3: Build and prove Python 3.14 runtime**

Run:

```bash
docker build -t my_django:v5.2.15-py3.14 backend
docker compose -f docker-compose.yml run --rm web python -VV
docker compose -f docker-compose-sy.yml run --rm web python -VV
docker compose -f docker-compose.yml run --rm web python -m django --version
docker compose -f docker-compose-sy.yml run --rm web python -m django --version
```

Expected: Python reports `3.14.x`; Django reports `5.2.15`.

- [ ] **Step 4: Run backend tests under Python 3.14**

Run:

```bash
docker compose -f docker-compose.yml run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py test myapp -v 1
docker compose -f docker-compose-sy.yml run --rm -e FNTL_TEST_REAL_SERVICES=1 web python manage.py test myapp -v 1
```

Expected: BT and SY backend test suites pass.

### Task 3: Full Regression And Cleanup

**Files:**
- No expected source edits unless verification exposes a compatibility issue.

- [ ] **Step 1: Run frontend checks**

Run:

```bash
cd frontend && npm run test:unit && npm run build
cd electron-client/frontend && npm run type-check
```

Expected: all commands exit `0`.

- [ ] **Step 2: Run FNTL regression**

Run:

```bash
FNTL_BACKEND_TEST_MODE=docker ./scripts/run-fntl-regression.sh
```

Expected: script exits `0` with `FNTL regression passed.`

- [ ] **Step 3: Cleanup services started by verification**

Run:

```bash
docker compose -f docker-compose.yml stop web db redis redis_stream
docker compose -f docker-compose-sy.yml stop web db redis redis_stream
rm -rf virtual-backend/test-results
```

Expected: no test result artifacts remain from Playwright, and no backend test stack is left running by this task.
