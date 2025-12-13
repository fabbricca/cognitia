"""
Cognitia Orchestrator Server

Simple HTTP/WebSocket server that bridges the K8s entrance to the Core.
All requests are trusted (no authentication at this layer).

Flow:
1. Receive message (text or audio) + userId + modelId
2. PARALLEL:
   - Thread 1: If audio → STT, else pass through
   - Thread 2: Fetch conversation history + personas
3. Build enriched system prompt
4. Send to LLM (Core)
5. Route response:
   - Text chat + short response → return text only
   - Text chat + long response → TTS (kokoro + optional RVC)
   - Phone call → always TTS
"""

import asyncio
import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator, Optional

import httpx
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

# Configuration from environment
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hf.co/TheBloke/Mythalion-13B-GGUF:Q4_K_M")
RVC_URL = os.getenv("RVC_URL", "http://localhost:5050")
TTS_VOICE = os.getenv("TTS_VOICE", "af_bella")
SHORT_RESPONSE_THRESHOLD = int(os.getenv("SHORT_RESPONSE_THRESHOLD", "100"))  # chars


class CommunicationType(str, Enum):
    TEXT = "text"
    AUDIO = "audio"
    PHONE = "phone"


class MessageRequest(BaseModel):
    """Request from the K8s entrance."""
    user_id: str
    model_id: str
    message: str  # Text message or base64 audio
    communication_type: CommunicationType = CommunicationType.TEXT
    conversation_history: list[dict] = []  # Previous messages
    system_prompt: str = "You are a helpful AI assistant."


class MessageResponse(BaseModel):
    """Response to the K8s entrance."""
    type: str  # "text" or "audio"
    content: str  # Text content or base64 audio
    sample_rate: int = 24000  # Only for audio


@dataclass
class ProcessingContext:
    """Context gathered during parallel processing."""
    user_message: str  # After STT if needed
    conversation_history: list[dict]
    enriched_system_prompt: str


# Thread pool for parallel processing
executor = ThreadPoolExecutor(max_workers=4)

# Lazy-loaded components
_asr_model = None
_tts_model = None


def get_asr_model():
    """Lazy load ASR model."""
    global _asr_model
    if _asr_model is None:
        from ..ASR import get_audio_transcriber
        _asr_model = get_audio_transcriber(engine_type="ctc")
        logger.info("ASR model loaded")
    return _asr_model


def get_tts_model():
    """Lazy load TTS model."""
    global _tts_model
    if _tts_model is None:
        from ..TTS import get_speech_synthesizer
        _tts_model = get_speech_synthesizer(TTS_VOICE)
        logger.info(f"TTS model loaded with voice: {TTS_VOICE}")
    return _tts_model


def transcribe_audio(audio_base64: str) -> str:
    """Convert audio to text using ASR."""
    asr = get_asr_model()
    
    # Decode base64 audio
    audio_bytes = base64.b64decode(audio_base64)
    audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    
    # Transcribe
    text = asr.transcribe(audio_array)
    logger.info(f"ASR transcription: {text}")
    return text


def synthesize_speech(text: str) -> tuple[bytes, int]:
    """Convert text to speech using TTS."""
    tts = get_tts_model()
    
    # Generate audio
    audio_float = tts.generate_speech_audio(text)
    
    # Convert to int16 bytes
    audio_int16 = (audio_float * 32767).astype(np.int16)
    audio_bytes = audio_int16.tobytes()
    
    return audio_bytes, tts.sample_rate


async def apply_rvc(audio_bytes: bytes, model_name: str) -> bytes:
    """Apply RVC voice conversion."""
    if not model_name:
        return audio_bytes
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{RVC_URL}/convert",
                files={"audio": ("audio.wav", audio_bytes, "audio/wav")},
                data={"model_name": model_name}
            )
            if response.status_code == 200:
                return response.content
            else:
                logger.warning(f"RVC conversion failed: {response.status_code}")
                return audio_bytes
    except Exception as e:
        logger.warning(f"RVC service unavailable: {e}")
        return audio_bytes


async def stream_llm_response(
    messages: list[dict],
    system_prompt: str
) -> AsyncGenerator[str, None]:
    """Stream response from Ollama."""
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    
    payload = {
        "model": OLLAMA_MODEL,
        "messages": full_messages,
        "stream": True,
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json=payload,
        ) as response:
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue


async def get_full_llm_response(
    messages: list[dict],
    system_prompt: str
) -> str:
    """Get complete response from Ollama."""
    full_response = ""
    async for chunk in stream_llm_response(messages, system_prompt):
        full_response += chunk
    return full_response


def process_stt_if_needed(
    message: str,
    communication_type: CommunicationType
) -> str:
    """Thread 1: Convert audio to text if needed."""
    if communication_type in (CommunicationType.AUDIO, CommunicationType.PHONE):
        return transcribe_audio(message)
    return message


def fetch_context(
    user_id: str,
    model_id: str,
    conversation_history: list[dict],
    system_prompt: str
) -> ProcessingContext:
    """Thread 2: Fetch conversation context and enrich system prompt.
    
    This is where you'd integrate:
    - User persona information
    - Model/character persona
    - Memory/entity extraction
    - Summarization of old messages
    
    For now, just pass through the provided data.
    """
    # TODO: Add database lookups, memory integration, etc.
    # For now, this is a pass-through
    
    enriched_prompt = system_prompt
    
    # Add user context if available
    # enriched_prompt = f"{system_prompt}\n\nUser context: ..."
    
    return ProcessingContext(
        user_message="",  # Will be filled by STT thread
        conversation_history=conversation_history,
        enriched_system_prompt=enriched_prompt
    )


# FastAPI app
app = FastAPI(title="Cognitia Orchestrator", version="1.0.0")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "orchestrator"}


@app.post("/process")
async def process_message(request: MessageRequest) -> MessageResponse:
    """
    Process a single message and return the response.
    
    This handles the complete flow:
    1. STT if audio
    2. Fetch context (parallel with STT)
    3. LLM generation
    4. TTS if needed
    """
    loop = asyncio.get_event_loop()
    
    # PARALLEL PROCESSING
    # Thread 1: STT if needed
    stt_future = loop.run_in_executor(
        executor,
        process_stt_if_needed,
        request.message,
        request.communication_type
    )
    
    # Thread 2: Fetch context
    context_future = loop.run_in_executor(
        executor,
        fetch_context,
        request.user_id,
        request.model_id,
        request.conversation_history,
        request.system_prompt
    )
    
    # Wait for both
    user_message, context = await asyncio.gather(stt_future, context_future)
    context.user_message = user_message
    
    # Build messages for LLM
    messages = context.conversation_history + [
        {"role": "user", "content": context.user_message}
    ]
    
    # Get LLM response
    llm_response = await get_full_llm_response(messages, context.enriched_system_prompt)
    
    # Decide whether to use TTS
    use_tts = False
    if request.communication_type == CommunicationType.PHONE:
        use_tts = True
    elif len(llm_response) > SHORT_RESPONSE_THRESHOLD:
        use_tts = True
    
    if use_tts:
        # Generate speech
        audio_bytes, sample_rate = await loop.run_in_executor(
            executor,
            synthesize_speech,
            llm_response
        )
        
        # Apply RVC if configured
        # TODO: Get RVC model from model_id configuration
        # audio_bytes = await apply_rvc(audio_bytes, rvc_model)
        
        return MessageResponse(
            type="audio",
            content=base64.b64encode(audio_bytes).decode("ascii"),
            sample_rate=sample_rate
        )
    else:
        return MessageResponse(
            type="text",
            content=llm_response
        )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for streaming/real-time communication.
    
    Messages are JSON with format:
    {
        "type": "text" | "audio",
        "user_id": "...",
        "model_id": "...",
        "message": "...",
        "system_prompt": "...",
        "conversation_history": [...]
    }
    
    Responses are streamed as JSON:
    {
        "type": "text_chunk" | "text_complete" | "audio",
        "content": "..."
    }
    """
    await websocket.accept()
    logger.info("WebSocket client connected")
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            msg_type = data.get("type", "text")
            user_id = data.get("user_id", "anonymous")
            model_id = data.get("model_id", "default")
            message = data.get("message", "")
            system_prompt = data.get("system_prompt", "You are a helpful AI assistant.")
            conversation_history = data.get("conversation_history", [])
            
            logger.info(f"Received message from {user_id}: {message[:50]}...")
            
            # Process STT if audio
            if msg_type == "audio":
                loop = asyncio.get_event_loop()
                message = await loop.run_in_executor(
                    executor,
                    transcribe_audio,
                    message
                )
                # Send transcription back
                await websocket.send_json({
                    "type": "transcription",
                    "content": message
                })
            
            # Build messages
            messages = conversation_history + [
                {"role": "user", "content": message}
            ]
            
            # Stream LLM response
            full_response = ""
            async for chunk in stream_llm_response(messages, system_prompt):
                full_response += chunk
                await websocket.send_json({
                    "type": "text_chunk",
                    "content": chunk
                })
            
            # Send completion
            await websocket.send_json({
                "type": "text_complete",
                "content": full_response
            })
            
            # Generate TTS if needed (for phone mode or long responses)
            comm_type = CommunicationType(data.get("communication_type", "text"))
            if comm_type == CommunicationType.PHONE or len(full_response) > SHORT_RESPONSE_THRESHOLD:
                loop = asyncio.get_event_loop()
                audio_bytes, sample_rate = await loop.run_in_executor(
                    executor,
                    synthesize_speech,
                    full_response
                )
                
                await websocket.send_json({
                    "type": "audio",
                    "content": base64.b64encode(audio_bytes).decode("ascii"),
                    "sample_rate": sample_rate
                })
    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the orchestrator server."""
    import uvicorn
    logger.info(f"Starting Cognitia Orchestrator on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
