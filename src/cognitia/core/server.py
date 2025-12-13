"""
Cognitia Core Server

HTTP/WebSocket server that runs on the GPU machine.
Exposes the orchestrator as an API for the K8s entrance to call.

All requests are trusted (no authentication at this layer).
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from .orchestrator import (
    Orchestrator,
    ProcessingRequest,
    ProcessingResponse,
    CommunicationType,
    get_orchestrator,
)


# -------------------------------------------------------------------------
# Pydantic Models for API
# -------------------------------------------------------------------------

class MessageRequest(BaseModel):
    """Request to process a message."""
    user_id: str
    model_id: str
    message: str  # Text or base64 audio
    communication_type: str = "text"  # "text", "audio", "phone"
    system_prompt: str = "You are a helpful AI assistant."
    conversation_history: list[dict] = []
    user_persona: Optional[str] = None
    model_name: str = "Assistant"
    voice: str = "af_bella"
    rvc_model_path: Optional[str] = None
    rvc_index_path: Optional[str] = None
    rvc_enabled: bool = False
    temperature: float = 0.8
    max_tokens: int = 2048


class MessageResponse(BaseModel):
    """Response from processing a message."""
    type: str  # "text" or "audio"
    content: str  # Text content or base64 audio
    text_content: str = ""  # Always the text content
    sample_rate: int = 24000


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    service: str = "cognitia-core"
    version: str = "3.0.0"


class TranscribeRequest(BaseModel):
    """Request to transcribe audio."""
    audio: str  # Base64-encoded audio


class TranscribeResponse(BaseModel):
    """Transcription response."""
    text: str


class SynthesizeRequest(BaseModel):
    """Request to synthesize speech."""
    text: str
    voice: str = "af_bella"
    rvc_model_path: Optional[str] = None
    rvc_enabled: bool = False


class SynthesizeResponse(BaseModel):
    """Speech synthesis response."""
    audio: str  # Base64-encoded audio
    sample_rate: int


# -------------------------------------------------------------------------
# Application
# -------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("Starting Cognitia Core...")
    # Pre-load models on startup
    orchestrator = get_orchestrator()
    logger.info("Cognitia Core started")
    yield
    # Cleanup
    orchestrator.shutdown()
    logger.info("Cognitia Core stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="Cognitia Core",
        description="GPU-side AI processing server (ASR, LLM, TTS, RVC)",
        version="3.0.0",
        lifespan=lifespan,
    )
    
    # CORS (allow all since we're internal)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    return app


app = create_app()


# -------------------------------------------------------------------------
# HTTP Endpoints
# -------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse()


@app.post("/process", response_model=MessageResponse, tags=["process"])
async def process_message(request: MessageRequest) -> MessageResponse:
    """
    Process a single message through the complete pipeline.
    
    Flow:
    1. STT if audio/phone
    2. Fetch context (parallel with STT)
    3. LLM generation
    4. TTS if needed (phone or long response)
    
    Returns text or audio based on communication type and response length.
    """
    orchestrator = get_orchestrator()
    
    try:
        # Convert to internal request
        proc_request = ProcessingRequest(
            user_id=request.user_id,
            model_id=request.model_id,
            message=request.message,
            communication_type=CommunicationType(request.communication_type),
            system_prompt=request.system_prompt,
            conversation_history=request.conversation_history,
            user_persona=request.user_persona,
            model_name=request.model_name,
            voice=request.voice,
            rvc_model_path=request.rvc_model_path,
            rvc_index_path=request.rvc_index_path,
            rvc_enabled=request.rvc_enabled,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        
        # Process
        response = await orchestrator.process(proc_request)
        
        return MessageResponse(
            type=response.type,
            content=response.content,
            text_content=response.text_content,
            sample_rate=response.sample_rate,
        )
        
    except Exception as e:
        logger.exception(f"Processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/transcribe", response_model=TranscribeResponse, tags=["asr"])
async def transcribe_audio(request: TranscribeRequest) -> TranscribeResponse:
    """
    Transcribe audio to text.
    
    Useful for voice message preview or when you need STT separately.
    """
    orchestrator = get_orchestrator()
    
    try:
        text = orchestrator.transcribe_audio(request.audio)
        return TranscribeResponse(text=text)
    except Exception as e:
        logger.exception(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/synthesize", response_model=SynthesizeResponse, tags=["tts"])
async def synthesize_speech(request: SynthesizeRequest) -> SynthesizeResponse:
    """
    Synthesize text to speech.
    
    Useful for TTS preview or when you need TTS separately.
    """
    orchestrator = get_orchestrator()
    loop = asyncio.get_event_loop()
    
    try:
        audio_bytes, sample_rate = await loop.run_in_executor(
            orchestrator.executor,
            orchestrator.synthesize_speech,
            request.text,
            request.voice,
        )
        
        # Apply RVC if requested
        if request.rvc_enabled and request.rvc_model_path:
            audio_bytes = await orchestrator.apply_rvc(
                audio_bytes,
                request.rvc_model_path,
                sample_rate,
            )
        
        import base64
        return SynthesizeResponse(
            audio=base64.b64encode(audio_bytes).decode("ascii"),
            sample_rate=sample_rate,
        )
    except Exception as e:
        logger.exception(f"Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------------
# WebSocket Endpoint (for streaming)
# -------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for streaming communication.
    
    Message format (client -> server):
    {
        "type": "process",
        "user_id": "...",
        "model_id": "...",
        "message": "...",
        "communication_type": "text|audio|phone",
        "system_prompt": "...",
        "conversation_history": [...],
        "voice": "...",
        ...
    }
    
    Response format (server -> client):
    {
        "type": "text_chunk",
        "content": "..."
    }
    {
        "type": "text_complete",
        "content": "full text"
    }
    {
        "type": "audio",
        "content": "base64...",
        "sample_rate": 24000
    }
    {
        "type": "error",
        "message": "..."
    }
    """
    await websocket.accept()
    logger.info("WebSocket client connected to core")
    
    orchestrator = get_orchestrator()
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            msg_type = data.get("type", "process")
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            
            if msg_type == "process":
                try:
                    # Build request
                    request = ProcessingRequest(
                        user_id=data.get("user_id", "anonymous"),
                        model_id=data.get("model_id", "default"),
                        message=data.get("message", ""),
                        communication_type=CommunicationType(data.get("communication_type", "text")),
                        system_prompt=data.get("system_prompt", "You are a helpful AI assistant."),
                        conversation_history=data.get("conversation_history", []),
                        user_persona=data.get("user_persona"),
                        model_name=data.get("model_name", "Assistant"),
                        voice=data.get("voice", "af_bella"),
                        rvc_model_path=data.get("rvc_model_path"),
                        rvc_index_path=data.get("rvc_index_path"),
                        rvc_enabled=data.get("rvc_enabled", False),
                        temperature=data.get("temperature", 0.8),
                        max_tokens=data.get("max_tokens", 2048),
                    )
                    
                    # Process with streaming
                    async def on_chunk(chunk: str):
                        await websocket.send_json({
                            "type": "text_chunk",
                            "content": chunk,
                        })
                    
                    async def on_complete(full_text: str):
                        await websocket.send_json({
                            "type": "text_complete",
                            "content": full_text,
                        })
                    
                    response = await orchestrator.process_streaming(
                        request,
                        on_text_chunk=on_chunk,
                        on_complete=on_complete,
                    )
                    
                    # Send audio if generated
                    if response.type == "audio":
                        await websocket.send_json({
                            "type": "audio",
                            "content": response.content,
                            "sample_rate": response.sample_rate,
                        })
                    
                except Exception as e:
                    logger.exception(f"WebSocket processing error: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                    })
            
            elif msg_type == "transcribe":
                try:
                    audio = data.get("audio", "")
                    text = orchestrator.transcribe_audio(audio)
                    await websocket.send_json({
                        "type": "transcription",
                        "content": text,
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Transcription error: {e}",
                    })
            
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })
    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from core")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")


# -------------------------------------------------------------------------
# CLI Entry Point
# -------------------------------------------------------------------------

def run(
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
):
    """Run the core server."""
    import uvicorn
    
    host = os.getenv("CORE_HOST", host)
    port = int(os.getenv("CORE_PORT", port))
    
    logger.info(f"Starting Cognitia Core on {host}:{port}")
    uvicorn.run(
        "cognitia.core.server:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    run()
