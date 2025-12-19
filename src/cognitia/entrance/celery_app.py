"""Celery application for background tasks."""

import os
from celery import Celery
from celery.schedules import crontab

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Create Celery app
celery_app = Celery(
    "cognitia_entrance",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["cognitia.entrance.tasks"]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    task_soft_time_limit=240,  # 4 minutes soft limit
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    broker_connection_retry_on_startup=True,
)

# Periodic tasks (Celery Beat schedule)
celery_app.conf.beat_schedule = {
    # Clean up expired tokens every hour
    "cleanup-expired-tokens": {
        "task": "cognitia.entrance.tasks.cleanup_expired_tokens",
        "schedule": crontab(minute=0),  # Every hour on the hour
    },
    # Aggregate daily metrics at midnight
    "aggregate-daily-metrics": {
        "task": "cognitia.entrance.tasks.aggregate_daily_metrics",
        "schedule": crontab(hour=0, minute=5),  # Daily at 00:05 UTC
    },
    # Check for expiring subscriptions daily
    "check-expiring-subscriptions": {
        "task": "cognitia.entrance.tasks.check_expiring_subscriptions",
        "schedule": crontab(hour=9, minute=0),  # Daily at 09:00 UTC
    },
    # Decay inactive relationships daily
    "decay-inactive-relationships": {
        "task": "cognitia.entrance.tasks.decay_inactive_relationships",
        "schedule": crontab(hour=3, minute=0),  # Daily at 03:00 UTC
    },
}

if __name__ == "__main__":
    celery_app.start()
