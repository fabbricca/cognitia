"""Main FastAPI application with integrated WebSocket bridge."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, AsyncGenerator

import httpx
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import verify_token
from .cache import cache, init_cache, close_cache
from .database import init_db, get_session, Character, Chat, Message
from .routes_auth import router as auth_router
from .routes_characters import router as characters_router
from .routes_chats import router as chats_router
from .schemas import HealthResponse

# Backend connection settings
BACKEND_HOST = os.getenv("COGNITIA_BACKEND_HOST", "10.0.0.15")
BACKEND_PORT = int(os.getenv("COGNITIA_BACKEND_PORT", "5555"))

# LLM API settings for text-only mode
LLM_API_URL = os.getenv("LLM_API_URL", "http://10.0.0.15:8080/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4")


async def stream_llm_response(
    messages: list[dict], 
    system_prompt: str
) -> AsyncGenerator[str, None]:
    """Stream response from LLM API."""
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    
    payload = {
        "model": LLM_MODEL,
        "messages": full_messages,
        "stream": True,
        "temperature": 0.8,
        "max_tokens": 1024,
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            LLM_API_URL,
            json=payload,
            headers=headers,
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue


import struct
import base64

# Protocol markers matching GPU backend network_io.py
TEXT_MESSAGE_FROM_CLIENT = 0xFFFFFFFF  # Client -> Server text
TEXT_MESSAGE_TO_CLIENT = 0xFFFFFFFE    # Server -> Client AI response
USER_TRANSCRIPTION_TO_CLIENT = 0xFFFFFFFD  # Server -> Client user speech transcription
KEEPALIVE_TO_CLIENT = 0xFFFFFFFC       # Server -> Client keepalive


class WebSocketBridge:
    """Manages WebSocket to TCP backend bridge connections.
    
    Protocol (little-endian, matching GPU backend network_io.py):
    
    Client -> Server:
      - Text: [0xFFFFFFFF (4 bytes)][length (4 bytes)][utf-8 text]
      - Audio: Raw int16 chunks (512 samples = 1024 bytes each)
    
    Server -> Client:
      - Text response: [0xFFFFFFFE (4 bytes)][length (4 bytes)][utf-8 text]
      - User transcription: [0xFFFFFFFD (4 bytes)][length (4 bytes)][utf-8 text]
      - Keepalive: [0xFFFFFFFC (4 bytes)][0 (4 bytes)]
      - Audio: [length (4 bytes)][sample_rate (4 bytes)][audio bytes]
      - Stop playback: [0 (4 bytes)][0 (4 bytes)]
    """
    
    def __init__(self, websocket: WebSocket, user_id: str):
        self.websocket = websocket
        self.user_id = user_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.running = False
    
    async def connect_to_backend(self) -> bool:
        """Establish TCP connection to GPU backend."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(BACKEND_HOST, BACKEND_PORT),
                timeout=10.0
            )
            logger.info(f"[{self.user_id}] Connected to backend {BACKEND_HOST}:{BACKEND_PORT}")
            return True
        except asyncio.TimeoutError:
            logger.error(f"[{self.user_id}] Backend connection timeout")
            return False
        except Exception as e:
            logger.error(f"[{self.user_id}] Backend connection failed: {e}")
            return False
    
    async def ws_to_backend(self):
        """Forward messages from WebSocket to TCP backend."""
        try:
            while self.running:
                try:
                    message = await self.websocket.receive_text()
                    msg = json.loads(message)
                    msg_type = msg.get("type", "")
                    
                    if msg_type == "text":
                        # Send text message: [0xFFFFFFFF][length][utf-8 text]
                        text = msg.get("message", "").encode('utf-8')
                        header = struct.pack("<II", TEXT_MESSAGE_FROM_CLIENT, len(text))
                        self.writer.write(header + text)
                        await self.writer.drain()
                        logger.debug(f"[{self.user_id}] Sent text to backend: {msg.get('message', '')[:50]}")
                    
                    elif msg_type == "audio":
                        # Send raw audio data (already int16 from client)
                        audio_data = base64.b64decode(msg.get("data", ""))
                        self.writer.write(audio_data)
                        await self.writer.drain()
                    
                    elif msg_type == "ping":
                        # Respond to ping directly
                        await self.websocket.send_json({"type": "pong"})
                    
                    elif msg_type == "stop_playback":
                        # Send stop command: [0][0]
                        self.writer.write(struct.pack("<II", 0, 0))
                        await self.writer.drain()
                    
                    else:
                        logger.debug(f"[{self.user_id}] Ignoring message type: {msg_type}")
                        
                except WebSocketDisconnect:
                    logger.info(f"[{self.user_id}] WebSocket disconnected")
                    break
                except json.JSONDecodeError:
                    await self.send_error("Invalid JSON")
                except Exception as e:
                    logger.error(f"[{self.user_id}] WS->Backend error: {e}")
                    break
        finally:
            self.running = False
    
    async def backend_to_ws(self):
        """Forward messages from TCP backend to WebSocket."""
        try:
            while self.running:
                # Read first 4 bytes to determine message type
                header1 = await self._read_exact(4)
                if not header1:
                    break
                
                first_value = struct.unpack("<I", header1)[0]
                
                # Check if this is a special message (text, transcription, keepalive)
                if first_value == TEXT_MESSAGE_TO_CLIENT:
                    # AI text response: [0xFFFFFFFE][length][utf-8 text]
                    length_bytes = await self._read_exact(4)
                    if not length_bytes:
                        break
                    length = struct.unpack("<I", length_bytes)[0]
                    
                    text_bytes = await self._read_exact(length)
                    if not text_bytes:
                        break
                    
                    text = text_bytes.decode('utf-8', errors='replace')
                    logger.debug(f"[{self.user_id}] Received AI text: {text[:50]}...")
                    
                    # Send as text chunks (stream to client)
                    await self.websocket.send_json({
                        "type": "text_chunk",
                        "chunk": text
                    })
                    await self.websocket.send_json({
                        "type": "text_complete",
                        "full_text": text
                    })
                
                elif first_value == USER_TRANSCRIPTION_TO_CLIENT:
                    # User transcription: [0xFFFFFFFD][length][utf-8 text]
                    length_bytes = await self._read_exact(4)
                    if not length_bytes:
                        break
                    length = struct.unpack("<I", length_bytes)[0]
                    
                    text_bytes = await self._read_exact(length)
                    if not text_bytes:
                        break
                    
                    text = text_bytes.decode('utf-8', errors='replace')
                    logger.debug(f"[{self.user_id}] Received transcription: {text}")
                    
                    await self.websocket.send_json({
                        "type": "transcription",
                        "text": text
                    })
                
                elif first_value == KEEPALIVE_TO_CLIENT:
                    # Keepalive: [0xFFFFFFFC][0] - just consume and ignore
                    await self._read_exact(4)  # Read the zero length
                    # Optionally send keepalive to websocket
                    await self.websocket.send_json({"type": "keepalive"})
                
                elif first_value == 0:
                    # Stop playback signal: [0][0]
                    await self._read_exact(4)  # Read second zero
                    await self.websocket.send_json({"type": "playback_stopped"})
                
                else:
                    # Audio data: first_value is the length, next 4 bytes is sample_rate
                    audio_length = first_value
                    
                    if audio_length > 10_000_000:  # 10MB limit
                        logger.error(f"[{self.user_id}] Audio too large: {audio_length}")
                        break
                    
                    sample_rate_bytes = await self._read_exact(4)
                    if not sample_rate_bytes:
                        break
                    sample_rate = struct.unpack("<I", sample_rate_bytes)[0]
                    
                    audio_bytes = await self._read_exact(audio_length)
                    if not audio_bytes:
                        break
                    
                    logger.debug(f"[{self.user_id}] Received audio: {audio_length} bytes, {sample_rate}Hz")
                    
                    # Send audio to WebSocket as base64
                    await self.websocket.send_json({
                        "type": "audio",
                        "data": base64.b64encode(audio_bytes).decode('ascii'),
                        "sampleRate": sample_rate,
                        "format": "int16"
                    })
                
        except Exception as e:
            logger.error(f"[{self.user_id}] Backend->WS error: {e}")
        finally:
            self.running = False
    
    async def _read_exact(self, n: int) -> Optional[bytes]:
        """Read exactly n bytes from the stream."""
        data = b""
        while len(data) < n:
            try:
                chunk = await asyncio.wait_for(
                    self.reader.read(n - len(data)),
                    timeout=30.0
                )
                if not chunk:
                    return None
                data += chunk
            except asyncio.TimeoutError:
                logger.warning(f"[{self.user_id}] Read timeout")
                return None
        return data
    
    async def send_error(self, message: str):
        """Send error message to WebSocket client."""
        await self.websocket.send_json({"type": "error", "message": message})
    
    async def close(self):
        """Close all connections."""
        self.running = False
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    await init_db()
    await init_cache()
    logger.info("Cognitia API server started")
    yield
    # Shutdown
    await close_cache()
    logger.info("Cognitia API server shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Cognitia API",
        description="Multi-character AI chat platform with voice support",
        version="3.0.0",
        lifespan=lifespan,
    )
    
    # CORS configuration
    origins = os.getenv("CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # API routes (prefix /api to match frontend expectations)
    app.include_router(auth_router, prefix="/api")
    app.include_router(characters_router, prefix="/api")
    app.include_router(chats_router, prefix="/api")
    
    # Favicon - return empty response to avoid 404
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)
    
    # Health check
    @app.get("/health", tags=["health"])
    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    async def health_check():
        """Health check endpoint."""
        return HealthResponse()
    
    # WebSocket endpoint (integrated bridge)
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time communication with GPU backend."""
        await websocket.accept()
        
        # Wait for auth message
        try:
            auth_msg = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=30.0
            )
            
            if auth_msg.get("type") != "auth":
                await websocket.send_json({"type": "error", "message": "First message must be auth"})
                await websocket.close()
                return
            
            token = auth_msg.get("token", "")
            user_id = verify_token(token)
            
            if not user_id:
                await websocket.send_json({"type": "error", "message": "Invalid token"})
                await websocket.close()
                return
            
            logger.info(f"WebSocket authenticated for user: {user_id}")
            await websocket.send_json({"type": "auth_success", "userId": user_id})
            
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "error", "message": "Auth timeout"})
            await websocket.close()
            return
        except Exception as e:
            logger.error(f"WebSocket auth error: {e}")
            await websocket.close()
            return
        
        # Create bridge to backend (optional - may not be available in K8s-only mode)
        bridge = WebSocketBridge(websocket, user_id)
        backend_available = await bridge.connect_to_backend()
        
        if not backend_available:
            # Backend not available - run in text-only mode with direct LLM API
            logger.warning(f"[{user_id}] Backend not available, running in text-only mode")
            await websocket.send_json({
                "type": "status", 
                "message": "Voice backend not available. Text chat only.",
                "mode": "text-only"
            })
            
            # State for text-only mode
            current_character_id: Optional[str] = None
            current_system_prompt = "You are a helpful AI assistant."
            conversation_history: list[dict] = []
            
            try:
                while True:
                    msg = await websocket.receive_json()
                    msg_type = msg.get("type")
                    
                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                    
                    elif msg_type == "character_switch":
                        # Update current character
                        current_character_id = msg.get("characterId")
                        current_system_prompt = msg.get("systemPrompt", "You are a helpful AI assistant.")
                        conversation_history = []  # Reset on character switch
                        logger.info(f"[{user_id}] Switched to character: {current_character_id}")
                        await websocket.send_json({
                            "type": "info",
                            "message": "Character switched"
                        })
                    
                    elif msg_type == "text":
                        user_message = msg.get("message", "").strip()
                        if not user_message:
                            continue
                        
                        # Add user message to history
                        conversation_history.append({"role": "user", "content": user_message})
                        
                        # Keep only last 10 messages to avoid token limits
                        if len(conversation_history) > 10:
                            conversation_history = conversation_history[-10:]
                        
                        # Stream LLM response
                        full_response = ""
                        try:
                            async for chunk in stream_llm_response(conversation_history, current_system_prompt):
                                full_response += chunk
                                await websocket.send_json({
                                    "type": "text_chunk",
                                    "chunk": chunk
                                })
                            
                            # Send completion
                            await websocket.send_json({
                                "type": "text_complete",
                                "full_text": full_response
                            })
                            
                            # Add assistant response to history
                            conversation_history.append({"role": "assistant", "content": full_response})
                            
                        except Exception as e:
                            logger.error(f"[{user_id}] LLM error: {e}")
                            await websocket.send_json({
                                "type": "error",
                                "message": f"LLM error: {str(e)}"
                            })
                    
                    else:
                        await websocket.send_json({
                            "type": "info", 
                            "message": f"Received {msg_type}, but voice features are offline"
                        })
            except WebSocketDisconnect:
                logger.info(f"[{user_id}] WebSocket disconnected (text-only mode)")
            return
        
        # Backend IS available - send status and start bridge
        logger.info(f"[{user_id}] Backend connected, starting voice bridge")
        await websocket.send_json({
            "type": "status",
            "message": "Voice backend connected. Full voice mode available.",
            "mode": "voice"
        })
        
        bridge.running = True
        
        # Run bidirectional forwarding
        try:
            await asyncio.gather(
                bridge.ws_to_backend(),
                bridge.backend_to_ws(),
            )
        finally:
            await bridge.close()
            logger.info(f"WebSocket closed for user: {user_id}")
    
    # Static files for web frontend (if exists) - must be last
    # In Docker, web files are at /app/web, in development they're relative to package
    web_dir = Path("/app/web")
    if not web_dir.exists():
        web_dir = Path(__file__).parent.parent.parent.parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")
    
    return app


# Create app instance for uvicorn
app = create_app()


def run():
    """Run the server."""
    import uvicorn
    uvicorn.run(
        "cognitia.api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("API_RELOAD", "false").lower() == "true",
    )


if __name__ == "__main__":
    run()
