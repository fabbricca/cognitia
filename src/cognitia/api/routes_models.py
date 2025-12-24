"""Model listing endpoints expected by the web UI."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends
from loguru import logger

from .orchestrator import get_orchestrator_url

from .auth import get_user_id

ORCHESTRATOR_URL = get_orchestrator_url()

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/voices")
async def list_voice_models(
    _user_id: UUID = Depends(get_user_id),
) -> dict[str, Any]:
    # Keep this simple and stable for the UI.
    models = [
        {"id": "af_bella", "name": "Bella", "description": "American female, warm and friendly", "language": "en", "type": "tts"},
        {"id": "af_nicole", "name": "Nicole", "description": "American female, professional", "language": "en", "type": "tts"},
        {"id": "af_sarah", "name": "Sarah", "description": "American female, casual", "language": "en", "type": "tts"},
        {"id": "af_sky", "name": "Sky", "description": "American female, youthful", "language": "en", "type": "tts"},
        {"id": "am_adam", "name": "Adam", "description": "American male, authoritative", "language": "en", "type": "tts"},
        {"id": "am_michael", "name": "Michael", "description": "American male, friendly", "language": "en", "type": "tts"},
        {"id": "bf_emma", "name": "Emma", "description": "British female, elegant", "language": "en", "type": "tts"},
        {"id": "bf_isabella", "name": "Isabella", "description": "British female, refined", "language": "en", "type": "tts"},
        {"id": "bm_george", "name": "George", "description": "British male, distinguished", "language": "en", "type": "tts"},
        {"id": "bm_lewis", "name": "Lewis", "description": "British male, articulate", "language": "en", "type": "tts"},
    ]
    return {"models": models}


@router.get("/rvc")
async def list_rvc_models(
    _user_id: UUID = Depends(get_user_id),
) -> dict[str, Any]:
    models: list[dict[str, Any]] = []

    # Best-effort: ask the GPU server / orchestrator for available RVC models.
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{ORCHESTRATOR_URL}/rvc-models")
            if response.status_code == 200:
                core_models = response.json()
                for model in core_models:
                    model_name = model.get("name", "")
                    pth_file = model.get("pth_file", "")
                    index_file = model.get("index_file")
                    if model_name and pth_file:
                        models.append(
                            {
                                "name": model_name,
                                "model_path": f"rvc_models/{model_name}/{pth_file}",
                                "index_path": f"rvc_models/{model_name}/{index_file}" if index_file else None,
                                "description": f"RVC model: {model_name}",
                            }
                        )
    except Exception as e:
        logger.warning(f"Failed to fetch RVC models from orchestrator: {e}")

    return {"models": models}
