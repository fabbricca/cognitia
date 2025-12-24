"""Memory worker service.

Consumes Redis Streams events (published by the orchestrator, or by the web tier
only on fallback) and performs async memory updates out-of-band.

Env:
- REDIS_URL: Redis connection string
- MEMORY_UPDATE_STREAM: stream key (default: cognitia:memory_updates)
- MEMORY_CONSUMER_GROUP: group name (default: memory-worker)
- MEMORY_CONSUMER_NAME: consumer name (default: hostname-pid)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from loguru import logger
from pydantic import BaseModel
import httpx

try:
    import redis.asyncio as redis  # type: ignore[import-not-found]

    REDIS_AVAILABLE = True
except Exception:  # pragma: no cover
    redis = None  # type: ignore
    REDIS_AVAILABLE = False


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MEMORY_UPDATE_STREAM = os.getenv("MEMORY_UPDATE_STREAM", "cognitia:memory_updates")
MEMORY_CONSUMER_GROUP = os.getenv("MEMORY_CONSUMER_GROUP", "memory-worker")
MEMORY_CONSUMER_NAME = os.getenv(
    "MEMORY_CONSUMER_NAME",
    f"{socket.gethostname()}-{os.getpid()}",
)
MEMORY_BLOCK_MS = int(os.getenv("MEMORY_BLOCK_MS", "5000"))
MEMORY_BATCH_SIZE = int(os.getenv("MEMORY_BATCH_SIZE", "10"))
MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8002").rstrip("/")


class HealthResponse(BaseModel):
    status: str
    redis: str
    stream: str
    memory_service: str
    last_event_ts: float | None = None


class _State:
    def __init__(self) -> None:
        self.redis: Any = None
        self.http: httpx.AsyncClient | None = None
        self.last_event_ts: float | None = None
        self._task: asyncio.Task[None] | None = None


state = _State()


async def _ensure_consumer_group(r: Any) -> None:
    try:
        await r.xgroup_create(name=MEMORY_UPDATE_STREAM, groupname=MEMORY_CONSUMER_GROUP, id="0-0", mkstream=True)
        logger.info(f"Created consumer group {MEMORY_CONSUMER_GROUP} on {MEMORY_UPDATE_STREAM}")
    except Exception as e:
        # BUSYGROUP is expected if it already exists
        if "BUSYGROUP" in str(e):
            return
        raise


async def _handle_event(fields: dict[str, Any]) -> None:
    payload_raw = fields.get("payload")
    if not isinstance(payload_raw, str) or not payload_raw:
        raise ValueError("missing payload")

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid payload json: {e}") from e

    if payload.get("type") != "memory_update":
        # Ignore unknown event types for forward compatibility.
        return

    user_id = str(payload.get("user_id", ""))
    character_id = str(payload.get("character_id", ""))
    user_text = str(payload.get("user_text", ""))
    assistant_text = str(payload.get("assistant_text", ""))

    if not user_id or not character_id or not user_text or not assistant_text:
        raise ValueError("payload missing required fields")

    ts = payload.get("ts")
    try:
        # Memory service expects a datetime; sending ISO is fine (pydantic parses it).
        timestamp = ts if isinstance(ts, str) and ts else datetime.now(timezone.utc).isoformat()
    except Exception:
        timestamp = datetime.now(timezone.utc).isoformat()

    ingest_req = {
        "user_id": user_id,
        "character_id": character_id,
        "user_message": user_text,
        "assistant_response": assistant_text,
        "extracted_facts": [],
        "timestamp": timestamp,
    }

    if state.http is None:
        raise RuntimeError("http client not initialized")

    url = f"{MEMORY_SERVICE_URL}/ingest"
    resp = await state.http.post(url, json=ingest_req)
    if resp.status_code >= 400:
        raise RuntimeError(f"memory ingest failed {resp.status_code}: {resp.text[:200]}")


async def _consume_loop() -> None:
    if not REDIS_AVAILABLE:
        logger.warning("redis not available; memory-worker is idle")
        return

    assert state.redis is not None

    await _ensure_consumer_group(state.redis)

    while True:
        try:
            resp = await state.redis.xreadgroup(
                groupname=MEMORY_CONSUMER_GROUP,
                consumername=MEMORY_CONSUMER_NAME,
                streams={MEMORY_UPDATE_STREAM: ">"},
                count=MEMORY_BATCH_SIZE,
                block=MEMORY_BLOCK_MS,
            )

            if not resp:
                continue

            # resp: [(stream, [(id, {field: value})...])]
            for _stream_name, messages in resp:
                for msg_id, fields in messages:
                    try:
                        await _handle_event(fields)
                        await state.redis.xack(MEMORY_UPDATE_STREAM, MEMORY_CONSUMER_GROUP, msg_id)
                        state.last_event_ts = time.time()
                    except Exception as e:
                        logger.exception(f"Failed processing message {msg_id}: {e}")
                        # Do not ack, allow retry.
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Consumer loop error: {e}; retrying soon")
            await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not REDIS_AVAILABLE or redis is None:
        yield
        return

    state.redis = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    state.http = httpx.AsyncClient(timeout=20.0)
    try:
        await state.redis.ping()
    except Exception as e:
        logger.warning(f"Redis ping failed ({e}); memory-worker will keep retrying")

    state._task = asyncio.create_task(_consume_loop())
    yield
    if state._task:
        state._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state._task
    if state.redis is not None:
        await state.redis.close()
    if state.http is not None:
        await state.http.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Cognitia Memory Worker", version="0.1.0", lifespan=lifespan)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        if not REDIS_AVAILABLE:
            return HealthResponse(
                status="degraded",
                redis="unavailable",
                stream=MEMORY_UPDATE_STREAM,
                memory_service="unknown",
            )

        redis_status = "unknown"
        try:
            if state.redis is None:
                redis_status = "disconnected"
            else:
                await state.redis.ping()
                redis_status = "ok"
        except Exception:
            redis_status = "error"

        status = "ok" if redis_status == "ok" else "degraded"

        mem_status = "unknown"
        if state.http is not None:
            try:
                r = await state.http.get(f"{MEMORY_SERVICE_URL}/health")
                mem_status = "ok" if r.status_code < 400 else f"error:{r.status_code}"
            except Exception:
                mem_status = "error"

        if status == "ok" and mem_status != "ok":
            status = "degraded"

        return HealthResponse(
            status=status,
            redis=redis_status,
            stream=MEMORY_UPDATE_STREAM,
            memory_service=mem_status,
            last_event_ts=state.last_event_ts,
        )

    return app


app = create_app()
