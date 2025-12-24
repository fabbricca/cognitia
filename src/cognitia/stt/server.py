"""STT service.

GPU-hosted speech-to-text using the ported legacy ONNX ASR pipelines.

Input/Output:
- Request accepts base64-encoded audio (WAV recommended).
- Response returns recognized text.

Env:
- STT_ENGINE: asr engine type (ctc|tdt)
- COGNITIA_RESOURCES_ROOT: base directory containing models/... (see cognitia.utils.resources)
"""

from __future__ import annotations

import base64
import io
import os

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..asr_core import get_audio_transcriber


class HealthResponse(BaseModel):
    status: str = "ok"


class TranscribeRequest(BaseModel):
    # Placeholder contract; actual implementation will likely accept
    # multipart audio or an object-store URL.
    audio_b64: str
    engine: str | None = None


class TranscribeResponse(BaseModel):
    text: str


def create_app() -> FastAPI:
    app = FastAPI(title="Cognitia STT", version="0.1.0")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        _ = os.getenv("STT_ENGINE", "")
        return HealthResponse(status="ok")

    @app.post("/v1/transcribe", response_model=TranscribeResponse)
    async def transcribe(req: TranscribeRequest) -> TranscribeResponse:
        if not req.audio_b64:
            raise HTTPException(status_code=400, detail="audio_b64 is required")

        try:
            raw = base64.b64decode(req.audio_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}") from e

        def _decode() -> tuple[np.ndarray, int]:
            import soundfile as sf  # type: ignore

            audio, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
            audio = audio[:, 0]
            return audio, int(sr)

        try:
            audio, sr = await run_in_threadpool(_decode)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to decode audio: {e}") from e

        engine = (req.engine or os.getenv("STT_ENGINE") or "ctc").strip() or "ctc"

        def _run_asr() -> str:
            transcriber = get_audio_transcriber(engine_type=engine)
            # The legacy ASR pipeline expects a specific sample rate from its YAML config.
            expected_sr = getattr(getattr(transcriber, "melspectrogram", None), "sample_rate", None)
            if expected_sr is not None and int(expected_sr) != int(sr):
                raise ValueError(f"Sample rate mismatch: expected {expected_sr}Hz, got {sr}")
            audio_np = np.asarray(audio, dtype=np.float32)
            return str(transcriber.transcribe(audio_np))

        try:
            text = await run_in_threadpool(_run_asr)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {e}") from e

        return TranscribeResponse(text=text)

    return app


app = create_app()
