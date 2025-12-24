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

    full_messages = [{"role": "system", "content": system_prompt}] + messages
    payload = {
        "model": ollama_model,
        "messages": full_messages,
        "stream": True,
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
