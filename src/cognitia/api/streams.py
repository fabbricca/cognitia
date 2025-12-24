"""Redis Streams publisher for async memory updates."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MEMORY_UPDATE_STREAM = os.getenv("MEMORY_UPDATE_STREAM", "cognitia:memory_updates")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryUpdatePublisher:
    def __init__(self) -> None:
        self._redis: Optional["redis.Redis"] = None

    async def connect(self) -> None:
        if not REDIS_AVAILABLE:
            logger.warning("Redis not available; memory update events disabled")
            return
        try:
            self._redis = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
            await self._redis.ping()
        except Exception as e:
            logger.warning(f"Redis connection failed ({e}); memory update events disabled")
            self._redis = None

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()

    async def publish_memory_update(
        self,
        *,
        user_id: str,
        character_id: str,
        chat_id: str,
        user_text: str,
        assistant_text: str,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        if self._redis is None:
            return

        payload: dict[str, Any] = {
            "type": "memory_update",
            "ts": _now_iso(),
            "user_id": user_id,
            "character_id": character_id,
            "chat_id": chat_id,
            "user_text": user_text,
            "assistant_text": assistant_text,
        }
        if meta:
            payload["meta"] = meta

        try:
            await self._redis.xadd(
                MEMORY_UPDATE_STREAM,
                {
                    "event": "memory_update",
                    "payload": json.dumps(payload),
                },
            )
        except Exception as e:
            logger.warning(f"Failed to publish memory update event: {e}")


publisher = MemoryUpdatePublisher()
