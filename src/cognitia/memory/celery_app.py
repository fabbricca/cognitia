"""Celery app configuration for background tasks."""

from celery import Celery
from celery.schedules import crontab

from config import settings

# Initialize Celery app
app = Celery(
    "cognitia_memory",
    broker=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0",
    backend=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0",
)

# Celery configuration
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour timeout
    task_soft_time_limit=3000,  # 50 minutes soft timeout
    worker_prefetch_multiplier=1,  # One task at a time
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
)

# Periodic task schedule
app.conf.beat_schedule = {
    # Auto-distill personas every 6 hours
    "auto-distill-personas": {
        "task": "celery_app.auto_distill_personas",
        "schedule": crontab(minute=0, hour="*/6"),  # Every 6 hours
    },
    # Prune old memories daily at 3 AM
    "prune-old-memories": {
        "task": "celery_app.prune_old_memories",
        "schedule": crontab(minute=0, hour=3),  # Daily at 3 AM
    },
}

# Autodiscover tasks
app.autodiscover_tasks(["celery_app"])
