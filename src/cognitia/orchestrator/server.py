"""Minimal GPU orchestrator stub.

This service is intended to run on the GPU host and be reachable from the
Kubernetes web tier over the LAN.

Contract (v1):
- Orchestrator receives already-authenticated requests (no JWT validation here).
- Streaming response is newline-delimited JSON (NDJSON):
    {"type":"token","text":"..."}\n
    {"type":"done"}\n
The entrance service converts token streams into sentence-level SSE.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

try:
    import redis.asyncio as redis  # type: ignore[import-not-found]

    REDIS_AVAILABLE = True
except Exception:  # pragma: no cover
    redis = None  # type: ignore
    REDIS_AVAILABLE = False


MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://127.0.0.1:8002").rstrip("/")
MEMORY_RETRIEVE_LIMIT = int(os.getenv("MEMORY_RETRIEVE_LIMIT", "8"))
MEMORY_CONTEXT_MAX_CHARS = int(os.getenv("MEMORY_CONTEXT_MAX_CHARS", "4000"))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MEMORY_UPDATE_STREAM = os.getenv("MEMORY_UPDATE_STREAM", "cognitia:memory_updates")

RVC_MODELS_DIR = Path(os.getenv("RVC_MODELS_DIR", "./rvc_models"))


class _State:
    def __init__(self) -> None:
        self.redis: Any = None


state = _State()


class HealthResponse(BaseModel):
    status: str = "ok"


class ChatStreamRequest(BaseModel):
    user_id: str
    chat_id: str
    character_id: str
    message: str = Field(min_length=1)
    system_prompt: Optional[str] = None
    history: Optional[list[dict[str, Any]]] = None


def _ndjson(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


async def _publish_memory_update(*, user_id: str, chat_id: str, character_id: str, user_text: str, assistant_text: str) -> None:
    """Best-effort Redis Streams publish; does not raise."""
    if not REDIS_AVAILABLE or redis is None:
        return
    if not user_id or not chat_id or not character_id:
        return
    if not user_text or not assistant_text:
        return

    payload = {
        "type": "memory_update",
        "user_id": user_id,
        "chat_id": chat_id,
        "character_id": character_id,
        "user_text": user_text,
        "assistant_text": assistant_text,
        "ts": datetime.now(timezone.utc).isoformat(),
        "meta": {"source": "orchestrator"},
    }

    r: Any = state.redis
    close_after = False
    try:
        if r is None:
            r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
            close_after = True
        await r.xadd(name=MEMORY_UPDATE_STREAM, fields={"payload": json.dumps(payload, ensure_ascii=False)})
    except Exception:
        return
    finally:
        if close_after:
            try:
                await r.close()
            except Exception:
                return


async def _ollama_token_stream(*, system_prompt: str, history: list[dict[str, Any]]) -> AsyncIterator[str]:
    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    def _get_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except Exception:
            return default

    def _get_float(name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except Exception:
            return default

    # Default sampling tuned to reduce repetition while keeping responses natural.
    # Can be overridden via env vars.
    options: dict[str, Any] = {
        "temperature": _get_float("OLLAMA_TEMPERATURE", 0.7),
        "top_p": _get_float("OLLAMA_TOP_P", 0.9),
        "top_k": _get_int("OLLAMA_TOP_K", 40),
        "repeat_penalty": _get_float("OLLAMA_REPEAT_PENALTY", 1.15),
        "repeat_last_n": _get_int("OLLAMA_REPEAT_LAST_N", 128),
    }

    num_ctx_raw = os.getenv("OLLAMA_NUM_CTX")
    if num_ctx_raw:
        try:
            options["num_ctx"] = int(num_ctx_raw)
        except Exception:
            pass

    payload = {
        "model": ollama_model,
        "messages": [{"role": "system", "content": system_prompt}] + history,
        "stream": True,
        "options": options,
    }

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{ollama_url}/api/chat", json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise HTTPException(status_code=502, detail=f"Ollama error: {body[:200]!r}")
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = data.get("message", {}).get("content", "")
                if content:
                    yield content
                if data.get("done"):
                    break


async def _retrieve_memory_context(*, user_id: str, character_id: str, query: str) -> str:
    """Best-effort memory retrieval; returns empty string on failure."""
    if not MEMORY_SERVICE_URL:
        return ""

    payload = {
        "user_id": user_id,
        "character_id": character_id,
        "query": query,
        "limit": MEMORY_RETRIEVE_LIMIT,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(f"{MEMORY_SERVICE_URL}/retrieve", json=payload)
            if resp.status_code >= 400:
                return ""
            data = resp.json()
            context = data.get("context")
            if not isinstance(context, str):
                return ""
            context = context.strip()
            if not context:
                return ""
            if len(context) > MEMORY_CONTEXT_MAX_CHARS:
                context = context[:MEMORY_CONTEXT_MAX_CHARS]
            return context
    except Exception:
        return ""


def create_app() -> FastAPI:
    app = FastAPI(title="Cognitia Orchestrator", version="0.1.0")

    @app.on_event("startup")
    async def _startup() -> None:
        if not REDIS_AVAILABLE or redis is None:
            state.redis = None
            return
        try:
            state.redis = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
            await state.redis.ping()
        except Exception:
            state.redis = None

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if state.redis is not None:
            try:
                await state.redis.close()
            finally:
                state.redis = None

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/rvc-models")
    async def list_rvc_models() -> list[dict[str, Any]]:
        """List available RVC models for the web tier.

        Response contract consumed by API [src/cognitia/api/routes_models.py]:
        [{"name": "<dir>", "pth_file": "<file.pth>", "index_file": "<file.index>|None"}, ...]
        """
        base = RVC_MODELS_DIR
        if not base.exists() or not base.is_dir():
            return []

        models: list[dict[str, Any]] = []

        for model_dir in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            pth_files = sorted([p for p in model_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pth"])
            if not pth_files:
                continue

            index_files = sorted([p for p in model_dir.iterdir() if p.is_file() and p.suffix.lower() == ".index"])

            models.append(
                {
                    "name": model_dir.name,
                    "pth_file": pth_files[0].name,
                    "index_file": index_files[0].name if index_files else None,
                }
            )

        return models

    @app.post("/v1/chat/stream")
    async def chat_stream(req: ChatStreamRequest):
        system_prompt = req.system_prompt or "You are a helpful AI assistant."
        history: list[dict[str, Any]] = list(req.history or [])
        history.append({"role": "user", "content": req.message})

        memory_context = await _retrieve_memory_context(
            user_id=req.user_id,
            character_id=req.character_id,
            query=req.message,
        )
        if memory_context:
            system_prompt = (
                system_prompt
                + "\n\nUse the following memory context when relevant."
                + "\n[MEMORY CONTEXT]\n"
                + memory_context
                + "\n[/MEMORY CONTEXT]\n"
            )

        async def gen() -> AsyncIterator[bytes]:
            assistant_text_parts: list[str] = []
            try:
                async for token in _ollama_token_stream(system_prompt=system_prompt, history=history):
                    assistant_text_parts.append(token)
                    yield _ndjson({"type": "token", "text": token})
                yield _ndjson({"type": "done"})

                assistant_text = "".join(assistant_text_parts).strip()
                if assistant_text:
                    asyncio.create_task(
                        _publish_memory_update(
                            user_id=req.user_id,
                            chat_id=req.chat_id,
                            character_id=req.character_id,
                            user_text=req.message.strip(),
                            assistant_text=assistant_text,
                        )
                    )
            except HTTPException:
                raise
            except Exception as e:
                yield _ndjson({"type": "error", "message": str(e)})
                yield _ndjson({"type": "done"})

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    return app


app = create_app()
