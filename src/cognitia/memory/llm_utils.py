"""LLM utilities for calling Ollama."""

import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


async def call_ollama(
    prompt: str,
    model: str = None,
    ollama_url: str = None,
    temperature: float = 0.3,
    timeout: float = 30.0,
    response_format: str | None = None,
) -> str:
    """Call Ollama API for LLM inference.

    Args:
        prompt: The prompt to send to the LLM
        model: Ollama model name (defaults to settings.OLLAMA_MODEL)
        ollama_url: Ollama server URL (defaults to settings.OLLAMA_URL)
        temperature: Sampling temperature (0.0-1.0)
        timeout: Request timeout in seconds

    Returns:
        LLM response text

    Raises:
        httpx.HTTPError: If the request fails
    """
    # Import here to avoid circular dependency
    from .config import settings

    # Use settings defaults if not provided
    if model is None:
        model = settings.OLLAMA_MODEL
    if ollama_url is None:
        ollama_url = settings.OLLAMA_URL

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            payload: Dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": 2048,
                },
            }

            # Ollama supports enforcing strict JSON output via `format: "json"`.
            # Only set this when callers explicitly expect JSON.
            if response_format is not None:
                payload["format"] = response_format

            response = await client.post(
                f"{ollama_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

    except httpx.HTTPError as e:
        logger.error(f"Ollama API call failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error calling Ollama: {e}")
        raise


def extract_json_from_response(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from LLM response that may contain markdown code blocks.

    Args:
        text: LLM response text

    Returns:
        Parsed JSON dict or None if parsing fails
    """
    json_text = _extract_json_like(text, want="object")
    if json_text is None:
        logger.warning(f"No JSON found in response: {text[:200]}")
        return None

    parsed = _parse_json_relaxed(json_text)
    if isinstance(parsed, dict):
        return parsed
    logger.error(f"Failed to parse JSON object from text: {json_text[:300]}")
    return None


def extract_json_array_from_response(text: str) -> Optional[list]:
    """Extract JSON array from LLM response.

    Args:
        text: LLM response text

    Returns:
        Parsed JSON array or None if parsing fails
    """
    json_text = _extract_json_like(text, want="array")
    if json_text is None:
        logger.warning(f"No JSON array found in response: {text[:200]}")
        return None

    parsed = _parse_json_relaxed(json_text)
    if isinstance(parsed, list):
        return parsed
    logger.error(f"Failed to parse JSON array from text: {json_text[:300]}")
    return None


def _extract_json_like(text: str, *, want: str) -> Optional[str]:
    """Extract a JSON object/array string from an LLM response.

    The response may include markdown code fences or additional prose.
    This function attempts to extract the first balanced JSON object/array.
    """
    if want not in {"object", "array"}:
        raise ValueError("want must be 'object' or 'array'")

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    candidate_source = fence_match.group(1) if fence_match else text

    open_char = "{" if want == "object" else "["
    close_char = "}" if want == "object" else "]"
    return _find_balanced(candidate_source, open_char=open_char, close_char=close_char)


def _find_balanced(text: str, *, open_char: str, close_char: str) -> Optional[str]:
    """Return the first balanced {...} or [...] substring, respecting quoted strings."""
    start = text.find(open_char)
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]

        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == open_char:
            depth += 1
            continue
        if ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
            continue

    return None


def _parse_json_relaxed(json_text: str) -> Any:
    """Parse JSON with small, safe repairs for common LLM issues.

    Repairs include:
    - stripping JS-style comments
    - removing trailing commas before } or ]
    """
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        pass

    repaired = json_text
    # Remove /* ... */ block comments
    repaired = re.sub(r"/\*.*?\*/", "", repaired, flags=re.DOTALL)
    # Remove // line comments
    repaired = re.sub(r"(^|\s)//.*?$", r"\1", repaired, flags=re.MULTILINE)
    # Remove trailing commas
    prev = None
    while prev != repaired:
        prev = repaired
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON after repair: {e}\nText: {repaired[:300]}")
        return None
