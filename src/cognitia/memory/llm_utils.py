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
    from config import settings

    # Use settings defaults if not provided
    if model is None:
        model = settings.OLLAMA_MODEL
    if ollama_url is None:
        ollama_url = settings.OLLAMA_URL

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": 2048,
                    },
                },
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
    # Try to find JSON in markdown code blocks first
    code_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    match = re.search(code_block_pattern, text, re.DOTALL)

    if match:
        json_text = match.group(1)
    else:
        # Try to find raw JSON object
        json_pattern = r"\{.*\}"
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            json_text = match.group(0)
        else:
            logger.warning(f"No JSON found in response: {text[:200]}")
            return None

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}\nText: {json_text[:200]}")
        return None


def extract_json_array_from_response(text: str) -> Optional[list]:
    """Extract JSON array from LLM response.

    Args:
        text: LLM response text

    Returns:
        Parsed JSON array or None if parsing fails
    """
    # Try to find JSON array in markdown code blocks first
    code_block_pattern = r"```(?:json)?\s*(\[.*?\])\s*```"
    match = re.search(code_block_pattern, text, re.DOTALL)

    if match:
        json_text = match.group(1)
    else:
        # Try to find raw JSON array
        json_pattern = r"\[.*\]"
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            json_text = match.group(0)
        else:
            logger.warning(f"No JSON array found in response: {text[:200]}")
            return None

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON array: {e}\nText: {json_text[:200]}")
        return None
