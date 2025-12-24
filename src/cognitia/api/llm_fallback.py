"""Text-only fallback helpers.

These are used when the GPU orchestrator isn't reachable.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx


async def stream_ollama_response(messages: list[dict], system_prompt: str) -> AsyncIterator[str]:
    """Stream response from Ollama (text-only fallback)."""
    ollama_url = os.getenv("OLLAMA_URL", "http://10.0.0.15:11434").rstrip("/")
    ollama_model = os.getenv("OLLAMA_MODEL", "hf.co/TheBloke/Mythalion-13B-GGUF:Q4_K_M")

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

    options: dict = {
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

    full_messages = [{"role": "system", "content": system_prompt}] + messages
    payload = {
        "model": ollama_model,
        "messages": full_messages,
        "stream": True,
        "options": options,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{ollama_url}/api/chat",
            json=payload,
        ) as response:
            async for line in response.aiter_lines():
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
