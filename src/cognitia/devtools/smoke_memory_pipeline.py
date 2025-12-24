"""Smoke test: full memory pipeline.

Validates the final design:
1) Orchestrator streams NDJSON tokens.
2) Orchestrator publishes a `memory_update` to Redis Streams.
3) Memory-worker consumes from the same stream and calls memory-service `/ingest`.

This smoke test checks (2) via Redis Streams and (3) indirectly via memory-worker
`/health.last_event_ts` advancing, and ensures memory-service `/health` is reachable.

Run:
  python -m cognitia.devtools.smoke_memory_pipeline

Env:
- ORCHESTRATOR_URL (default: http://127.0.0.1:8080)
- MEMORY_WORKER_URL (default: http://127.0.0.1:8005)
- MEMORY_SERVICE_URL (default: http://127.0.0.1:8002)
- REDIS_URL (default: redis://localhost:6379/0)
- MEMORY_UPDATE_STREAM (default: cognitia:memory_updates)
- SMOKE_TIMEOUT_S (default: 30)
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import httpx

try:
    import redis.asyncio as redis  # type: ignore[import-not-found]
except Exception as e:  # pragma: no cover
    raise RuntimeError(f"redis package not available: {e}")


ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8080").rstrip("/")
MEMORY_WORKER_URL = os.getenv("MEMORY_WORKER_URL", "http://127.0.0.1:8005").rstrip("/")
MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8002").rstrip("/")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MEMORY_UPDATE_STREAM = os.getenv("MEMORY_UPDATE_STREAM", "cognitia:memory_updates")
SMOKE_TIMEOUT_S = float(os.getenv("SMOKE_TIMEOUT_S", "30"))


@dataclass(frozen=True)
class SmokeIds:
    user_id: str
    chat_id: str
    character_id: str


async def _orchestrator_stream(*, ids: SmokeIds, message: str) -> str:
    payload = {
        "user_id": ids.user_id,
        "chat_id": ids.chat_id,
        "character_id": ids.character_id,
        "message": message,
        "system_prompt": "You are a helpful assistant. Reply with one short sentence.",
        "history": [],
    }

    parts: list[str] = []
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{ORCHESTRATOR_URL}/v1/chat/stream", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("type") == "token":
                    parts.append(str(obj.get("text", "")))
                elif obj.get("type") == "done":
                    break

    return "".join(parts).strip()


async def _redis_wait_for_event(*, ids: SmokeIds, user_text: str) -> dict:
    deadline = asyncio.get_running_loop().time() + SMOKE_TIMEOUT_S

    r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        while asyncio.get_running_loop().time() < deadline:
            entries = await r.xrevrange(MEMORY_UPDATE_STREAM, count=50)
            for _entry_id, fields in entries:
                raw = fields.get("payload")
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") != "memory_update":
                    continue
                if payload.get("chat_id") != ids.chat_id:
                    continue
                if payload.get("user_id") != ids.user_id:
                    continue
                if payload.get("character_id") != ids.character_id:
                    continue
                if payload.get("user_text") != user_text:
                    continue
                return payload
            await asyncio.sleep(0.25)

        raise TimeoutError("Timed out waiting for memory_update in Redis")
    finally:
        await r.close()


async def _get_memory_worker_health(client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{MEMORY_WORKER_URL}/health", timeout=5.0)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("memory-worker /health returned non-object")
    return data


async def _wait_for_worker_consume(*, before_ts: float | None) -> dict:
    deadline = asyncio.get_running_loop().time() + SMOKE_TIMEOUT_S
    async with httpx.AsyncClient(timeout=None) as client:
        while asyncio.get_running_loop().time() < deadline:
            h = await _get_memory_worker_health(client)
            last_ts = h.get("last_event_ts")
            if isinstance(last_ts, (int, float)):
                if before_ts is None or last_ts > before_ts:
                    return h
            await asyncio.sleep(0.5)

    raise TimeoutError("Timed out waiting for memory-worker to consume event")


async def main() -> None:
    ids = SmokeIds(
        user_id=f"smoke-user-{uuid4().hex}",
        chat_id=f"smoke-chat-{uuid4().hex}",
        character_id=f"smoke-character-{uuid4().hex}",
    )

    user_text = f"smoke pipeline {datetime.now(timezone.utc).isoformat()}"

    print(f"ORCHESTRATOR_URL={ORCHESTRATOR_URL}")
    print(f"MEMORY_WORKER_URL={MEMORY_WORKER_URL}")
    print(f"MEMORY_SERVICE_URL={MEMORY_SERVICE_URL}")
    print(f"REDIS_URL={REDIS_URL}")
    print(f"MEMORY_UPDATE_STREAM={MEMORY_UPDATE_STREAM}")
    print(f"chat_id={ids.chat_id}")

    async with httpx.AsyncClient(timeout=None) as client:
        # Preflight health checks (explicit, so failures are clear)
        mw_health = await _get_memory_worker_health(client)
        before_ts = mw_health.get("last_event_ts")
        mem = await client.get(f"{MEMORY_SERVICE_URL}/health", timeout=5.0)
        mem.raise_for_status()

    assistant_text = await _orchestrator_stream(ids=ids, message=user_text)
    if not assistant_text:
        raise RuntimeError("Orchestrator returned empty assistant output")

    _ = await _redis_wait_for_event(ids=ids, user_text=user_text)
    mw_after = await _wait_for_worker_consume(before_ts=before_ts if isinstance(before_ts, (int, float)) else None)

    if mw_after.get("memory_service") not in ("ok",):
        raise RuntimeError(f"memory-worker reports memory_service={mw_after.get('memory_service')!r}")

    print("OK: orchestrator published, worker consumed, memory service reachable")


if __name__ == "__main__":
    asyncio.run(main())
