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


class WebSocketBridge:
    """Manages WebSocket to TCP backend bridge connections."""
    
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
                    
                    # Convert to backend protocol
                    binary_msg = self._encode_for_backend(msg)
                    self.writer.write(binary_msg)
                    await self.writer.drain()
                except WebSocketDisconnect:
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
                # Read message length (4 bytes)
                length_bytes = await self.reader.read(4)
                if not length_bytes:
                    break
                
                length = int.from_bytes(length_bytes, 'big')
                if length > 10_000_000:  # 10MB limit
                    logger.error(f"[{self.user_id}] Message too large: {length}")
                    break
                
                # Read message body
                data = await self.reader.read(length)
                if len(data) < length:
                    break
                
                # Convert to WebSocket JSON
                ws_msg = self._decode_from_backend(data)
                await self.websocket.send_json(ws_msg)
                
        except Exception as e:
            logger.error(f"[{self.user_id}] Backend->WS error: {e}")
        finally:
            self.running = False
    
    async def send_error(self, message: str):
        """Send error message to WebSocket client."""
        await self.websocket.send_json({"type": "error", "message": message})
    
    def _encode_for_backend(self, msg: dict) -> bytes:
        """Encode WebSocket message for TCP backend."""
        msg_type = msg.get("type", "")
        
        # Message type markers (matching backend protocol)
        TYPE_MARKERS = {
            "text": b'\x01',
            "audio": b'\x02', 
            "character_switch": b'\x03',
            "call_start": b'\x04',
            "call_end": b'\x05',
            "stop_playback": b'\x06',
        }
        
        marker = TYPE_MARKERS.get(msg_type, b'\x00')
        
        if msg_type == "text":
            payload = msg.get("message", "").encode('utf-8')
        elif msg_type == "audio":
            import base64
            payload = base64.b64decode(msg.get("data", ""))
        elif msg_type == "character_switch":
            payload = json.dumps({
                "system_prompt": msg.get("systemPrompt", ""),
                "voice_model": msg.get("voiceModel", "cognitia"),
                "rvc_model_path": msg.get("rvcModelPath"),
                "rvc_index_path": msg.get("rvcIndexPath"),
            }).encode('utf-8')
        else:
            payload = json.dumps(msg).encode('utf-8')
        
        # Length-prefixed message: [marker (1)] + [length (4)] + [payload]
        return marker + len(payload).to_bytes(4, 'big') + payload
    
    def _decode_from_backend(self, data: bytes) -> dict:
        """Decode TCP backend message to WebSocket JSON."""
        if len(data) < 1:
            return {"type": "error", "message": "Empty message"}
        
        marker = data[0]
        payload = data[1:]
        
        # Response type markers
        RESPONSE_TYPES = {
            0x10: "text_chunk",
            0x11: "text_complete",
            0x12: "audio",
            0x13: "transcription",
            0x14: "status",
            0x15: "error",
        }
        
        msg_type = RESPONSE_TYPES.get(marker, "unknown")
        
        if msg_type == "audio":
            import base64
            return {
                "type": msg_type,
                "data": base64.b64encode(payload).decode('ascii'),
                "format": "wav"
            }
        elif msg_type in ("text_chunk", "text_complete", "transcription"):
            return {
                "type": msg_type,
                "text": payload.decode('utf-8'),
            }
        else:
            try:
                return {"type": msg_type, **json.loads(payload.decode('utf-8'))}
            except:
                return {"type": msg_type, "data": payload.decode('utf-8', errors='replace')}
    
    async def close(self):
        """Close all connections."""
        self.running = False
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()


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
