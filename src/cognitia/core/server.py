"""
Cognitia Core Server

HTTP/WebSocket server that runs on the GPU machine.
Exposes the orchestrator as an API for the K8s entrance to call.

All requests are trusted (no authentication at this layer).
"""

import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
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
    persona_prompt: Optional[str] = None  # Detailed character biography/lorebook
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


class RvcModelUploadResponse(BaseModel):
    """Response from RVC model upload."""
    model_name: str
    pth_path: str
    index_path: Optional[str] = None
    message: str


# RVC models directory (from environment or default)
RVC_MODELS_DIR = Path(os.environ.get("RVC_MODELS_DIR", "/home/iberu/Documents/cognitia/rvc_models"))


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
            persona_prompt=request.persona_prompt,
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


@app.post("/upload-rvc-model", response_model=RvcModelUploadResponse, tags=["rvc"])
async def upload_rvc_model(
    model_name: str = Form(...),
    pth_file: UploadFile = File(...),
    index_file: Optional[UploadFile] = File(None),
) -> RvcModelUploadResponse:
    """
    Upload an RVC voice model (.pth and optional .index file).
    
    Files are saved to the RVC models directory in the format expected by the RVC service:
    - rvc_models/{model_name}/{model_name}.pth
    - rvc_models/{model_name}/{index_file_name}.index (if provided)
    
    Args:
        model_name: Name for the RVC model (used as directory name)
        pth_file: The .pth model file
        index_file: Optional .index file for better quality
    
    Returns:
        Information about the uploaded model
    """
    # Validate file extensions
    if not pth_file.filename.endswith('.pth'):
        raise HTTPException(status_code=400, detail="pth_file must have .pth extension")
    
    if index_file and not index_file.filename.endswith('.index'):
        raise HTTPException(status_code=400, detail="index_file must have .index extension")
    
    # Sanitize model name (remove path separators and special chars)
    safe_model_name = "".join(c for c in model_name if c.isalnum() or c in ('_', '-')).strip()
    if not safe_model_name:
        raise HTTPException(status_code=400, detail="Invalid model name")
    
    try:
        # Create model directory
        model_dir = RVC_MODELS_DIR / safe_model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        
        # Save .pth file
        pth_path = model_dir / f"{safe_model_name}.pth"
        with open(pth_path, "wb") as f:
            content = await pth_file.read()
            f.write(content)
        logger.info(f"Saved RVC model: {pth_path}")
        
        # Save .index file if provided
        index_path = None
        if index_file:
            # Keep original index filename (RVC needs it)
            index_path = model_dir / index_file.filename
            with open(index_path, "wb") as f:
                content = await index_file.read()
                f.write(content)
            logger.info(f"Saved RVC index: {index_path}")
        
        return RvcModelUploadResponse(
            model_name=safe_model_name,
            pth_path=str(pth_path),
            index_path=str(index_path) if index_path else None,
            message=f"Successfully uploaded RVC model '{safe_model_name}'"
        )
        
    except Exception as e:
        logger.exception(f"Failed to upload RVC model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload model: {str(e)}")


@app.get("/rvc-models", tags=["rvc"])
async def list_rvc_models() -> list[dict]:
    """
    List all available RVC models.
    
    Returns:
        List of model info dictionaries
    """
    models = []
    if RVC_MODELS_DIR.exists():
        for model_dir in RVC_MODELS_DIR.iterdir():
            if model_dir.is_dir():
                pth_files = list(model_dir.glob("*.pth"))
                index_files = list(model_dir.glob("*.index"))
                if pth_files:
                    models.append({
                        "name": model_dir.name,
                        "pth_file": pth_files[0].name if pth_files else None,
                        "index_file": index_files[0].name if index_files else None,
                    })
    return models


@app.delete("/rvc-models/{model_name}", tags=["rvc"])
async def delete_rvc_model(model_name: str) -> dict:
    """
    Delete an RVC model.
    
    Args:
        model_name: Name of the model to delete
    
    Returns:
        Confirmation message
    """
    model_dir = RVC_MODELS_DIR / model_name
    if not model_dir.exists():
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    
    try:
        shutil.rmtree(model_dir)
        logger.info(f"Deleted RVC model: {model_name}")
        return {"message": f"Successfully deleted RVC model '{model_name}'"}
    except Exception as e:
        logger.exception(f"Failed to delete RVC model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")


# -------------------------------------------------------------------------
# WebSocket Endpoint (for streaming)
# -------------------------------------------------------------------------

async def _process_with_sentence_streaming(
    websocket: WebSocket,
    orchestrator: "Orchestrator",
    request: "ProcessingRequest",
    with_audio: bool = True,
):
    """
    Process a request with sentence-by-sentence streaming.
    
    For each sentence:
    1. Send text_chunk with the sentence
    2. If with_audio, synthesize and send audio for the sentence
    
    At the end, send text_complete with full response.
    """
    import asyncio
    import base64
    
    loop = asyncio.get_event_loop()
    
    # First, handle STT if needed (parallel with context)
    stt_future = loop.run_in_executor(
        orchestrator.executor,
        orchestrator.process_stt_if_needed,
        request.message,
        request.communication_type,
    )
    context_future = loop.run_in_executor(
        orchestrator.executor,
        orchestrator.fetch_context,
        request,
    )
    user_message, context = await asyncio.gather(stt_future, context_future)
    context.user_message = user_message
    context.enriched_system_prompt = orchestrator.enrich_system_prompt(context)
    
    # Build messages for LLM
    messages = context.conversation.conversation_history + [
        {"role": "user", "content": context.user_message}
    ]
    
    # Send typing indicator
    await websocket.send_json({
        "type": "typing",
        "model_name": context.model.name,
    })
    
    # Stream sentence-by-sentence with batching for short sentences
    full_response = ""
    sentence_count = 0
    pending_text = ""  # Buffer for short sentences
    all_audio_chunks = []  # For RVC batching
    rvc_enabled = context.model.rvc_enabled and context.model.rvc_model_path
    
    logger.info(f"RVC enabled for streaming: {rvc_enabled}, model: {context.model.rvc_model_path}")
    
    async def send_chunk(text: str, is_final: bool = False):
        """Send a text chunk and optionally audio."""
        nonlocal sentence_count
        sentence_count += 1
        
        # Send the text
        await websocket.send_json({
            "type": "text_chunk",
            "content": text,
            "sentence_index": sentence_count,
        })
        
        # Generate audio if enabled
        if with_audio and text.strip():
            try:
                audio_bytes, sample_rate = await loop.run_in_executor(
                    orchestrator.executor,
                    orchestrator.synthesize_speech,
                    text,
                    context.model.voice,
                )
                
                if rvc_enabled:
                    # Accumulate audio for batch RVC at the end
                    all_audio_chunks.append((audio_bytes, sample_rate))
                else:
                    # No RVC - send audio immediately
                    await websocket.send_json({
                        "type": "audio",
                        "content": base64.b64encode(audio_bytes).decode("ascii"),
                        "sample_rate": sample_rate,
                        "sentence_index": sentence_count,
                    })
            except Exception as e:
                logger.warning(f"TTS failed for chunk: {e}")
    
    async for sentence in orchestrator.stream_sentences(
        messages,
        context.enriched_system_prompt,
        persona_prompt=context.model.persona_prompt,
        communication_type=request.communication_type,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    ):
        full_response += sentence + " "
        
        # Count words in the sentence
        word_count = len(sentence.split())
        
        if word_count >= 10:
            # Long enough sentence - send any pending text first, then this sentence
            if pending_text:
                await send_chunk(pending_text.strip())
                pending_text = ""
            await send_chunk(sentence)
        else:
            # Short sentence - add to pending buffer
            pending_text += sentence + " "
            
            # If we have 2+ sentences buffered, send them together
            # Count sentences by looking for sentence-ending punctuation
            sentence_ends = pending_text.count('.') + pending_text.count('!') + pending_text.count('?')
            if sentence_ends >= 2:
                await send_chunk(pending_text.strip())
                pending_text = ""
    
    # Send any remaining pending text
    if pending_text.strip():
        await send_chunk(pending_text.strip())
    
    # Send complete message
    await websocket.send_json({
        "type": "text_complete",
        "content": full_response.strip(),
    })
    
    # If RVC enabled, do batch conversion and send single audio
    if rvc_enabled and all_audio_chunks:
        try:
            import numpy as np
            
            # Combine all audio chunks
            combined_audio = b''.join(chunk[0] for chunk in all_audio_chunks)
            sample_rate = all_audio_chunks[0][1]  # All should have same rate
            
            logger.info(f"Applying RVC to combined audio: {len(combined_audio)} bytes")
            
            # Apply RVC to combined audio
            rvc_audio = await orchestrator.apply_rvc(
                combined_audio,
                context.model.rvc_model_path,
                sample_rate,
            )
            
            # Send single combined audio
            await websocket.send_json({
                "type": "audio",
                "content": base64.b64encode(rvc_audio).decode("ascii"),
                "sample_rate": sample_rate,
                "sentence_index": 0,  # Single combined audio
            })
            
            logger.info(f"Sent RVC audio: {len(rvc_audio)} bytes")
        except Exception as e:
            logger.exception(f"RVC batch processing failed: {e}")


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
                        persona_prompt=data.get("persona_prompt"),
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
                    
                    logger.info(f"Processing request: communication_type={request.communication_type}, with_audio={request.communication_type in (CommunicationType.AUDIO, CommunicationType.PHONE)}")
                    logger.info(f"RVC settings: enabled={request.rvc_enabled}, model_path={request.rvc_model_path}")
                    
                    # Decide streaming behavior based on communication type
                    # Audio input -> Audio output, Text input -> Text output
                    if request.communication_type == CommunicationType.PHONE:
                        # Phone mode: Stream sentence-by-sentence with TTS for each
                        await _process_with_sentence_streaming(
                            websocket, orchestrator, request, with_audio=True
                        )
                    elif request.communication_type == CommunicationType.AUDIO:
                        # Audio message: Reply with audio
                        await _process_with_sentence_streaming(
                            websocket, orchestrator, request, with_audio=True
                        )
                    else:
                        # Text mode: Reply with text only, no audio
                        await _process_with_sentence_streaming(
                            websocket, orchestrator, request, with_audio=False
                        )
                    
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
