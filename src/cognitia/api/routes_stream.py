"""Sentence-level SSE endpoints.

This is the first step toward the new architecture:
- Web tier (this service) authenticates.
- GPU orchestrator receives authenticated requests.
- Text responses stream back via SSE at sentence granularity.
- Memory updates are published asynchronously to Redis Streams.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_user_id
from .database import Character, Chat, Message, get_session
from .llm_fallback import stream_ollama_response
from .orchestrator import get_orchestrator_url
from .streams import publisher


router = APIRouter(prefix="/chat", tags=["chat"])


class ChatStreamRequest(BaseModel):
    chat_id: UUID
    character_id: UUID
    message: str
    prefer_orchestrator: bool = True


_SENTENCE_RE = re.compile(r"(?s)(.*?)([.!?]+\s+|\n+)")


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def _iter_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    buf = text
    while True:
        match = _SENTENCE_RE.match(buf)
        if match is None:
            break
        head = (match.group(1) + match.group(2)).strip()
        if head:
            sentences.append(head)
        buf = buf[match.end() :]
    return sentences


async def _load_chat_context(
    *,
    chat_id: UUID,
    character_id: UUID,
    user_id: UUID,
    session: AsyncSession,
    limit_messages: int = 10,
) -> tuple[str, list[dict[str, str]]]:
    # Verify chat ownership (via character)
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Chat.character_id == character_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    character = await session.get(Character, character_id)
    if character is None or character.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    msgs_result = await session.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .limit(limit_messages)
    )
    msgs = list(reversed(msgs_result.scalars().all()))
    messages = [{"role": m.role, "content": m.content} for m in msgs if m.content]
    return character.system_prompt, messages


async def _stream_from_orchestrator(
    *,
    orchestrator_url: str,
    user_id: str,
    chat_id: str,
    character_id: str,
    message: str,
    system_prompt: str,
    history: list[dict[str, str]],
) -> AsyncIterator[str]:
    """Best-effort streaming from GPU orchestrator.

    Contract: orchestrator responds with newline-delimited JSON objects:
      {"type": "token", "text": "..."}
      {"type": "done"}
    """
    endpoint = f"{orchestrator_url}/v1/chat/stream"
    payload = {
        "user_id": user_id,
        "chat_id": chat_id,
        "character_id": character_id,
        "message": message,
        "system_prompt": system_prompt,
        "history": history,
    }

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", endpoint, json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RuntimeError(f"orchestrator stream failed {resp.status_code}: {body[:200]!r}")

            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "token":
                    text = str(data.get("text", ""))
                    if text:
                        yield text
                elif data.get("type") == "done":
                    break


@router.post("/stream")
async def chat_stream(
    req: ChatStreamRequest,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session),
):
    """Stream assistant response as sentence-level SSE."""
    chat_id = req.chat_id
    character_id = req.character_id
    user_text = req.message.strip()
    prefer_orchestrator = req.prefer_orchestrator

    if not user_text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="message is required")

    system_prompt, history = await _load_chat_context(
        chat_id=chat_id,
        character_id=character_id,
        user_id=user_id,
        session=session,
    )

    orchestrator_url = get_orchestrator_url()

    async def gen() -> AsyncIterator[bytes]:
        full_text = ""
        buffer = ""
        used_orchestrator = False

        yield _sse("meta", {"chat_id": str(chat_id), "character_id": str(character_id)})
        yield _sse("status", {"state": "streaming"})

        try:
            token_stream: Optional[AsyncIterator[str]] = None
            if prefer_orchestrator:
                try:
                    token_stream = _stream_from_orchestrator(
                        orchestrator_url=orchestrator_url,
                        user_id=str(user_id),
                        chat_id=str(chat_id),
                        character_id=str(character_id),
                        message=user_text,
                        system_prompt=system_prompt,
                        history=history,
                    )
                    used_orchestrator = True
                except Exception as e:
                    logger.warning(f"Orchestrator stream unavailable, falling back to Ollama: {e}")
                    token_stream = None

            if token_stream is None:
                token_stream = stream_ollama_response(history + [{"role": "user", "content": user_text}], system_prompt)

            async for token in token_stream:
                full_text += token
                buffer += token
                sentences = _iter_sentences(buffer)
                if sentences:
                    # Drain buffer by repeatedly consuming matches.
                    for s in sentences:
                        yield _sse("sentence", {"text": s})
                    # Recompute remainder by removing all sentence-matched prefixes.
                    # (This is cheap because buffer is relatively small.)
                    remainder = buffer
                    while True:
                        m = _SENTENCE_RE.match(remainder)
                        if m is None:
                            break
                        remainder = remainder[m.end() :]
                    buffer = remainder

            # Flush remainder
            remainder = buffer.strip()
            if remainder:
                yield _sse("sentence", {"text": remainder})
                full_text += ""  # already counted via tokens

            yield _sse("done", {"ok": True})

            # Orchestrator takes ownership of publishing memory updates.
            # Only publish from the web tier when we fall back to local generation.
            if not used_orchestrator:
                await publisher.publish_memory_update(
                    user_id=str(user_id),
                    character_id=str(character_id),
                    chat_id=str(chat_id),
                    user_text=user_text,
                    assistant_text=full_text.strip(),
                    meta={"source": "ollama_fallback"},
                )

        except Exception as e:
            logger.error(f"SSE stream failed: {e}")
            yield _sse("error", {"message": "stream failed"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
