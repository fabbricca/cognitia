"""Main FastAPI application with integrated WebSocket bridge."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .auth import verify_token
from .cache import cache, init_cache, close_cache
from .database import init_db
from .routes_auth import router as auth_router
from .routes_characters import router as characters_router
from .routes_chats import router as chats_router
from .schemas import HealthResponse

# Backend connection settings
BACKEND_HOST = os.getenv("COGNITIA_BACKEND_HOST", "10.0.0.15")
BACKEND_PORT = int(os.getenv("COGNITIA_BACKEND_PORT", "5555"))


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
    
    # API routes
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(characters_router, prefix="/api/v1")
    app.include_router(chats_router, prefix="/api/v1")
    
    # Health check
    @app.get("/health", tags=["health"])
    @app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
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
        
        # Create bridge to backend
        bridge = WebSocketBridge(websocket, user_id)
        
        if not await bridge.connect_to_backend():
            await websocket.send_json({"type": "error", "message": "Backend connection failed"})
            await websocket.close()
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
