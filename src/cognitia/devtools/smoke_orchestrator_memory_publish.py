"""Smoke test: orchestrator publishes memory_update events to Redis Streams.

This checks the final-design responsibility split:
- Orchestrator publishes `memory_update` events to Redis Streams.
- Memory worker consumes those events and ingests them into the memory service.

This tool verifies the *publish* part end-to-end without needing web-tier auth.

Run:
  python -m cognitia.devtools.smoke_orchestrator_memory_publish

Env (override as needed):
- ORCHESTRATOR_URL (default: http://127.0.0.1:8080)
- REDIS_URL (default: redis://localhost:6379/0)
- MEMORY_UPDATE_STREAM (default: cognitia:memory_updates)
- SMOKE_TIMEOUT_S (default: 20)
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
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MEMORY_UPDATE_STREAM = os.getenv("MEMORY_UPDATE_STREAM", "cognitia:memory_updates")
SMOKE_TIMEOUT_S = float(os.getenv("SMOKE_TIMEOUT_S", "20"))


@dataclass(frozen=True)
class SmokeIds:
    user_id: str
    chat_id: str
    character_id: str


async def _stream_orchestrator(*, ids: SmokeIds, message: str) -> str:
    payload = {
        "user_id": ids.user_id,
        "chat_id": ids.chat_id,
        "character_id": ids.character_id,
        "message": message,
        "system_prompt": "You are a helpful assistant. Reply with one short sentence.",
        "history": [],
    }

    assistant_parts: list[str] = []
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{ORCHESTRATOR_URL}/v1/chat/stream", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                t = obj.get("type")
                if t == "token":
                    text = str(obj.get("text", ""))
                    assistant_parts.append(text)
                elif t == "done":
                    break
    return "".join(assistant_parts).strip()


async def _wait_for_published_event(*, ids: SmokeIds, user_text: str) -> dict:
    deadline = asyncio.get_running_loop().time() + SMOKE_TIMEOUT_S

    r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        # Start from latest entries and poll until we see our unique chat_id.
        while asyncio.get_running_loop().time() < deadline:
            entries = await r.xrevrange(MEMORY_UPDATE_STREAM, count=25)
            for _entry_id, fields in entries:
                payload_raw = fields.get("payload")
                if not payload_raw:
                    continue
                try:
                    payload = json.loads(payload_raw)
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

        raise TimeoutError(f"Timed out waiting for memory_update event on {MEMORY_UPDATE_STREAM}")
    finally:
        await r.close()


async def main() -> None:
    ids = SmokeIds(
        user_id=f"smoke-user-{uuid4().hex}",
        chat_id=f"smoke-chat-{uuid4().hex}",
        character_id=f"smoke-character-{uuid4().hex}",
    )

    user_text = f"smoke test message {datetime.now(timezone.utc).isoformat()}"
    print(f"ORCHESTRATOR_URL={ORCHESTRATOR_URL}")
    print(f"REDIS_URL={REDIS_URL}")
    print(f"MEMORY_UPDATE_STREAM={MEMORY_UPDATE_STREAM}")
    print(f"chat_id={ids.chat_id}")

    assistant_text = await _stream_orchestrator(ids=ids, message=user_text)
    if not assistant_text:
        raise RuntimeError("Orchestrator returned empty assistant output")

    payload = await _wait_for_published_event(ids=ids, user_text=user_text)

    # Minimal asserts
    assert payload.get("assistant_text"), "assistant_text missing"
    print("OK: orchestrator streamed response and published memory_update")


if __name__ == "__main__":
    asyncio.run(main())
