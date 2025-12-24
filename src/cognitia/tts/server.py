"""TTS service.

GPU-hosted text-to-speech using the ported legacy ONNX pipelines.

Input/Output:
- Request accepts text and optional voice.
- Response returns base64-encoded WAV (PCM16) + sample_rate.

Env:
- TTS_VOICE: default voice
- COGNITIA_RESOURCES_ROOT: base directory containing models/... (see cognitia.utils.resources)
- RVC_SERVICE_URL: optional RVC microservice (default http://rvc:5050)
"""

from __future__ import annotations

import base64
import os
import threading
import wave
from io import BytesIO
from typing import Any, Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..tts_core import get_speech_synthesizer

try:
    from ..tts_core.rvc_service import RVCServiceClient

    _RVC_CLIENT_AVAILABLE = True
except Exception:  # pragma: no cover
    RVCServiceClient = None  # type: ignore
    _RVC_CLIENT_AVAILABLE = False


class HealthResponse(BaseModel):
    status: str = "ok"


class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None

    # Optional: apply voice conversion via external RVC service.
    rvc_model_name: Optional[str] = None
    rvc_f0_method: str = "rmvpe"
    rvc_f0_up_key: int = 0
    rvc_index_rate: float = 0.5
    rvc_filter_radius: int = 3
    rvc_rms_mix_rate: float = 0.25
    rvc_protect: float = 0.33


class SynthesizeResponse(BaseModel):
    audio_wav_b64: str
    sample_rate: int
    voice: str
    used_rvc: bool = False


class _State:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._synth_by_voice: dict[str, Any] = {}


state = _State()


def _float32_to_wav_pcm16(audio: np.ndarray, sample_rate: int) -> bytes:
    audio_1d = np.asarray(audio, dtype=np.float32).reshape(-1)
    audio_1d = np.nan_to_num(audio_1d, nan=0.0, posinf=0.0, neginf=0.0)
    audio_1d = np.clip(audio_1d, -1.0, 1.0)
    pcm16 = (audio_1d * 32767.0).astype(np.int16)

    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _get_synth(voice: str) -> Any:
    with state._lock:
        synth = state._synth_by_voice.get(voice)
        if synth is None:
            synth = get_speech_synthesizer(voice=voice)
            state._synth_by_voice[voice] = synth
        return synth


def create_app() -> FastAPI:
    app = FastAPI(title="Cognitia TTS", version="0.1.0")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        _ = os.getenv("TTS_VOICE", "")
        return HealthResponse(status="ok")

    @app.post("/v1/synthesize", response_model=SynthesizeResponse)
    async def synthesize(req: SynthesizeRequest) -> SynthesizeResponse:
        text = (req.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")

        voice = (req.voice or os.getenv("TTS_VOICE", "cognitia")).strip() or "cognitia"

        def _run_tts() -> tuple[np.ndarray, int]:
            synth = _get_synth(voice)
            audio = np.asarray(synth.generate_speech_audio(text), dtype=np.float32)
            sample_rate = int(getattr(synth, "sample_rate", 24000))
            return audio, sample_rate

        audio, sample_rate = await run_in_threadpool(_run_tts)

        used_rvc = False
        if req.rvc_model_name and _RVC_CLIENT_AVAILABLE:
            rvc_url = os.getenv("RVC_SERVICE_URL", "http://rvc:5050")

            client_cls = RVCServiceClient
            if client_cls is None:
                # Best-effort: skip if optional dependency is unavailable.
                client_cls = None

            def _run_rvc() -> np.ndarray:
                if client_cls is None:
                    return audio
                client = client_cls(service_url=rvc_url, model_name=req.rvc_model_name)
                if not client.initialize():
                    return audio
                client.set_params(
                    f0_method=req.rvc_f0_method,
                    f0_up_key=req.rvc_f0_up_key,
                    index_rate=req.rvc_index_rate,
                    filter_radius=req.rvc_filter_radius,
                    rms_mix_rate=req.rvc_rms_mix_rate,
                    protect=req.rvc_protect,
                )
                return np.asarray(client.convert(audio, sample_rate), dtype=np.float32)

            converted = await run_in_threadpool(_run_rvc)
            # If conversion failed, client returns original audio; still safe.
            if converted is not audio:
                audio = converted
                used_rvc = True

        wav_bytes = _float32_to_wav_pcm16(audio, sample_rate)
        audio_wav_b64 = base64.b64encode(wav_bytes).decode("utf-8")
        return SynthesizeResponse(audio_wav_b64=audio_wav_b64, sample_rate=sample_rate, voice=voice, used_rvc=used_rvc)

    return app


app = create_app()
