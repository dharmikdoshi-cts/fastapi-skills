---
name: fastapi-background-tasks
description: >
  Implement background task patterns for FastAPI including FastAPI's built-in
  BackgroundTasks for lightweight work, Celery with Redis for heavy/distributed
  tasks, and async task patterns. Use this skill whenever the user asks about
  background tasks, async jobs, task queues, Celery integration, sending emails
  in background, long-running tasks, worker processes, or "fire and forget"
  patterns. Also trigger for "BackgroundTasks", "celery worker", "task queue",
  "async email", "deferred work", or "job processing". Python 3.12+.
---

# FastAPI Background Tasks Skill

Lightweight BackgroundTasks + Celery for heavy/distributed work. Python 3.12+.

---

## When to Use What

| Scenario | Use | Why |
|----------|-----|-----|
| Send email after signup | `BackgroundTasks` | Quick, no external deps |
| Log analytics event | `BackgroundTasks` | Fire-and-forget, fast |
| Process uploaded file | Celery | Could take minutes |
| Generate PDF report | Celery | CPU-intensive |
| Sync data with 3rd party | Celery | Retries, error handling |
| Scheduled/periodic jobs | Celery Beat | Cron-like scheduling |

Rule of thumb: if it takes under 5 seconds and doesn't need retries, use `BackgroundTasks`. Otherwise, use Celery.

---

## FastAPI BackgroundTasks (Built-in)

### Basic Usage

```python
from fastapi import APIRouter, BackgroundTasks
from app.api.dependencies import UserServiceDep
from app.schemas.common import StandardResponse
from app.utils.logger import setup_logger

router = APIRouter()
logger = setup_logger("tasks")


async def send_welcome_email(email: str, name: str):
    """Runs after response is sent to client."""
    logger.info("Sending welcome email", extra={"email": email})
    # await email_service.send(to=email, template="welcome", name=name)


@router.post("/register", response_model=StandardResponse, status_code=201)
async def register(
    data: RegisterRequest,
    service: UserServiceDep,
    background_tasks: BackgroundTasks,
):
    user = await service.create_user(data)

    # Queued — runs AFTER response is returned
    background_tasks.add_task(send_welcome_email, user.email, user.full_name)

    return StandardResponse(code=201, data=user, message="Registration successful")
```

### Multiple Background Tasks

```python
@router.post("/orders", response_model=StandardResponse, status_code=201)
async def create_order(
    data: OrderCreate,
    service: OrderServiceDep,
    background_tasks: BackgroundTasks,
):
    order = await service.create_order(data)

    # All run sequentially after response
    background_tasks.add_task(send_order_confirmation, order.id)
    background_tasks.add_task(update_inventory, order.items)
    background_tasks.add_task(notify_warehouse, order.id)

    return StandardResponse(code=201, data=order, message="Order placed")
```

### BackgroundTasks in Dependencies

```python
from typing import Annotated
from fastapi import BackgroundTasks, Depends

BgTasks = Annotated[BackgroundTasks, Depends()]

# Cleaner endpoint signatures
@router.post("/users")
async def create_user(data: UserCreate, service: UserServiceDep, bg: BgTasks):
    user = await service.create_user(data)
    bg.add_task(send_welcome_email, user.email, user.full_name)
    return StandardResponse(code=201, data=user)
```

### Important: BackgroundTasks Limitations

- Runs in the **same process** — if server restarts, task is lost
- No **retries** — if it fails, it fails silently
- No **monitoring** — can't check task status
- No **distributed** — runs on the instance that received the request
- Blocks the worker if task is synchronous (use async functions)

---

## Celery (Heavy/Distributed Tasks)

### Setup

```bash
poetry add celery[redis]
```

### Celery App Configuration

```python
# app/worker/celery_app.py
from celery import Celery
from app.config.settings import settings

celery_app = Celery(
    "worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,           # retry if worker dies mid-task
    worker_prefetch_multiplier=1,  # fair scheduling
    result_expires=3600,           # results expire in 1 hour
)

# Auto-discover tasks in all modules
celery_app.autodiscover_tasks(["app.worker.tasks"])
```

### Task Definitions

```python
# app/worker/tasks.py
from app.worker.celery_app import celery_app
import logging

logger = logging.getLogger("celery.tasks")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_task(self, to: str, subject: str, body: str):
    """Send email with automatic retries."""
    try:
        logger.info("Sending email to %s", to)
        # email_client.send(to=to, subject=subject, body=body)
    except Exception as exc:
        logger.error("Email failed, retrying: %s", str(exc))
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2)
def process_file_task(self, file_path: str, user_id: int):
    """Process uploaded file (CPU-intensive)."""
    try:
        logger.info("Processing file %s for user %d", file_path, user_id)
        # result = heavy_processing(file_path)
        # store_result(user_id, result)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task
def generate_report_task(report_type: str, params: dict):
    """Generate PDF report."""
    logger.info("Generating %s report", report_type)
    # pdf = report_generator.create(report_type, **params)
    # storage.upload(pdf)
```

### Calling Tasks from Endpoints

```python
# api/v1/endpoints/reports.py
from fastapi import APIRouter
from app.worker.tasks import generate_report_task, send_email_task
from app.schemas.common import StandardResponse

router = APIRouter()


@router.post("/reports/generate", response_model=StandardResponse)
async def request_report(data: ReportRequest, user: CurrentUser):
    # dispatch to Celery — returns immediately
    task = generate_report_task.delay(
        report_type=data.report_type,
        params=data.params,
    )

    return StandardResponse(
        data={"task_id": task.id},
        message="Report generation started",
    )


@router.get("/reports/status/{task_id}", response_model=StandardResponse)
async def check_report_status(task_id: str):
    from celery.result import AsyncResult
    result = AsyncResult(task_id)

    return StandardResponse(data={
        "task_id": task_id,
        "status": result.status,        # PENDING, STARTED, SUCCESS, FAILURE
        "result": result.result if result.ready() else None,
    })
```

### Running Celery Worker

```bash
# Start worker
poetry run celery -A app.worker.celery_app worker --loglevel=info

# Start beat (for periodic tasks)
poetry run celery -A app.worker.celery_app beat --loglevel=info
```

### Periodic Tasks (Celery Beat)

```python
# app/worker/celery_app.py (add to config)
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "cleanup-expired-tokens": {
        "task": "app.worker.tasks.cleanup_expired_tokens",
        "schedule": crontab(hour=2, minute=0),  # daily at 2 AM
    },
    "send-daily-digest": {
        "task": "app.worker.tasks.send_daily_digest",
        "schedule": crontab(hour=8, minute=0),   # daily at 8 AM
    },
    "sync-external-data": {
        "task": "app.worker.tasks.sync_external_data",
        "schedule": 300.0,  # every 5 minutes
    },
}
```

---

## Docker Compose with Celery

```yaml
# docker-compose.yml
services:
  app:
    build: .
    ports: ["8000:8000"]
    depends_on: [db, redis]
    environment:
      DATABASE_URL: postgresql+asyncpg://user:pass@db/appdb
      REDIS_URL: redis://redis:6379

  celery-worker:
    build: .
    command: celery -A app.worker.celery_app worker --loglevel=info
    depends_on: [db, redis]
    environment:
      DATABASE_URL: postgresql+asyncpg://user:pass@db/appdb
      REDIS_URL: redis://redis:6379

  celery-beat:
    build: .
    command: celery -A app.worker.celery_app beat --loglevel=info
    depends_on: [redis]
    environment:
      REDIS_URL: redis://redis:6379

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: appdb

  redis:
    image: redis:7-alpine
```

---

## Project Directory Addition

```
app/
├── worker/
│   ├── __init__.py
│   ├── celery_app.py       # Celery configuration
│   └── tasks.py            # Task definitions
```

---

## Quick Checklist

- [ ] `BackgroundTasks` for fast fire-and-forget (under 5s)
- [ ] Celery for heavy, distributed, or retriable tasks
- [ ] `task_acks_late=True` for reliability
- [ ] `max_retries` + `default_retry_delay` on critical tasks
- [ ] Task status endpoint for long-running jobs
- [ ] Celery Beat for periodic/scheduled tasks
- [ ] Docker Compose includes worker + beat services
- [ ] Celery tasks log with structured logger