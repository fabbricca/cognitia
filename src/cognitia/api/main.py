"""
Cognitia API - K8s Entrance

This is the frontend-facing API that handles:
- Authentication (JWT)
- REST endpoints for characters, chats, messages
- WebSocket proxy to GPU orchestrator
- Static file serving for web UI

All authenticated requests are proxied to the GPU orchestrator.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

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
from .memory_client import memory_client
from .routes_auth import router as auth_router
from .routes_characters import router as characters_router
from .routes_chats import router as chats_router
from .routes_memory import router as memory_router
from .schemas import HealthResponse

# Orchestrator connection settings
# Keep backward compatibility with existing k8s env naming.
ORCHESTRATOR_URL = os.getenv(
    "COGNITIA_ORCHESTRATOR_URL",
    os.getenv("COGNITIA_CORE_URL", "http://10.0.0.15:8080"),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    await init_db()
    await init_cache()
    logger.info("Cognitia API started")
    yield
    await close_cache()
    logger.info("Cognitia API shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="Cognitia API",
        description="Voice assistant API with authentication and GPU backend proxy",
        version="3.0.0",
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    # Routers define their own prefixes (e.g. /auth, /characters, /chats, /memory),
    # so we mount them once under /api.
    app.include_router(auth_router, prefix="/api")
    app.include_router(characters_router, prefix="/api")
    app.include_router(chats_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    
    # Favicon
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)
    
    # Health check
    @app.get("/health", tags=["health"])
    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    async def health_check():
        """Health check endpoint."""
        # Check memory service availability
        memory_status = "unavailable"
        try:
            is_available = await memory_client.check_health()
            if is_available:
                memory_status = "healthy"
        except Exception as e:
            logger.debug(f"Memory service health check failed: {e}")
            memory_status = "unavailable"

        return HealthResponse(memory_service=memory_status)
    
    # WebSocket endpoint - proxy to orchestrator
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """
        WebSocket endpoint for real-time communication.
        
        1. Authenticates the client
        2. Proxies messages to/from the GPU orchestrator
        """
        await websocket.accept()
        
        # Authenticate
        try:
            auth_msg = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=30.0
            )
            
            if auth_msg.get("type") != "auth":
                await websocket.send_json({
                    "type": "error",
                    "message": "First message must be auth"
                })
                await websocket.close()
                return
            
            token = auth_msg.get("token", "")
            user_id = await verify_token(token)
            
            if not user_id:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid token"
                })
                await websocket.close()
                return
            
            logger.info(f"WebSocket authenticated: {user_id}")
            await websocket.send_json({
                "type": "auth_success",
                "userId": user_id
            })
            
        except asyncio.TimeoutError:
            await websocket.send_json({
                "type": "error",
                "message": "Auth timeout"
            })
            await websocket.close()
            return
        except Exception as e:
            logger.error(f"WebSocket auth error: {e}")
            await websocket.close()
            return
        
        # Try to connect to orchestrator
        orchestrator_ws_url = ORCHESTRATOR_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
        
        try:
            async with httpx.AsyncClient() as client:
                # Check if orchestrator is available
                try:
                    health_resp = await client.get(f"{ORCHESTRATOR_URL}/health", timeout=5.0)
                    orchestrator_available = health_resp.status_code == 200
                except:
                    orchestrator_available = False
            
            if orchestrator_available:
                # Connect to orchestrator WebSocket and bridge
                await bridge_to_orchestrator(
                    websocket, user_id, orchestrator_ws_url
                )
            else:
                # Fallback to text-only mode using direct LLM
                logger.warning(f"Orchestrator not available, using text-only mode")
                await websocket.send_json({
                    "type": "status",
                    "message": "Voice backend not available. Text chat only.",
                    "mode": "text-only"
                })
                await text_only_mode(websocket, user_id)
                
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: {user_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await websocket.close()

    return app


async def bridge_to_orchestrator(
    client_ws: WebSocket,
    user_id: str,
    orchestrator_url: str
):
    """Bridge client WebSocket to orchestrator WebSocket."""
    import websockets
    
    await client_ws.send_json({
        "type": "status",
        "message": "Voice backend connected.",
        "mode": "voice"
    })
    
    try:
        async with websockets.connect(orchestrator_url) as backend_ws:
            async def forward_to_backend():
                """Forward client messages to orchestrator."""
                try:
                    while True:
                        msg = await client_ws.receive_json()
                        msg_type = msg.get("type", "")
                        
                        logger.info(f"Received client message: type={msg_type}, characterId={msg.get('characterId')}, keys={list(msg.keys())}")
                        
                        if msg_type == "ping":
                            await client_ws.send_json({"type": "pong"})
                            continue
                        
                        # Enrich message with user_id
                        msg["user_id"] = user_id
                        
                        # Get character info if switching or sending message
                        if msg_type in ("text", "audio", "character_switch"):
                            char_id = msg.get("characterId")
                            if char_id:
                                logger.info(f"User selected character ID: {char_id}")
                                async with get_session() as session:
                                    char = await session.get(Character, char_id)
                                    if char:
                                        logger.info(f"Character details: name={char.name}, rvc_model_path={char.rvc_model_path}")
                                        msg["system_prompt"] = char.system_prompt
                                        msg["model_id"] = char_id
                                        msg["model_name"] = char.name
                                        msg["voice"] = char.voice_model
                                        # Include RVC voice conversion settings
                                        if char.rvc_model_path:
                                            msg["rvc_model_path"] = char.rvc_model_path
                                            msg["rvc_enabled"] = True
                                            logger.info(f"Character {char.name} using RVC model: {char.rvc_model_path}")
                                        else:
                                            msg["rvc_enabled"] = False
                                            logger.info(f"Character {char.name} has no RVC model")
                        
                        logger.info(f"Sending message to Core: type={msg_type}, rvc_enabled={msg.get('rvc_enabled')}, rvc_model_path={msg.get('rvc_model_path')}")
                        await backend_ws.send(json.dumps(msg))
                        
                except WebSocketDisconnect:
                    pass
            
            async def forward_to_client():
                """Forward orchestrator messages to client."""
                try:
                    async for message in backend_ws:
                        data = json.loads(message)
                        await client_ws.send_json(data)
                except:
                    pass
            
            # Run both directions
            await asyncio.gather(
                forward_to_backend(),
                forward_to_client()
            )
            
    except Exception as e:
        logger.error(f"Orchestrator bridge error: {e}")
        # Fall back to text-only mode
        await client_ws.send_json({
            "type": "status",
            "message": "Connection to backend lost. Text chat only.",
            "mode": "text-only"
        })
        await text_only_mode(client_ws, user_id)


async def text_only_mode(websocket: WebSocket, user_id: str):
    """Handle text-only mode when orchestrator is unavailable."""
    
    # State
    current_system_prompt = "You are a helpful AI assistant."
    conversation_history: list[dict] = []
    
    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif msg_type == "character_switch":
                char_id = msg.get("characterId")
                if char_id:
                    async with get_session() as session:
                        char = await session.get(Character, char_id)
                        if char:
                            current_system_prompt = char.system_prompt
                            conversation_history = []
                            logger.info(f"[{user_id}] Switched to character: {char.name}")
                            await websocket.send_json({
                                "type": "info",
                                "message": f"Switched to {char.name}"
                            })
            
            elif msg_type == "text":
                user_message = msg.get("message", "").strip()
                if not user_message:
                    continue
                
                conversation_history.append({"role": "user", "content": user_message})
                
                # Keep last 10 messages
                if len(conversation_history) > 10:
                    conversation_history = conversation_history[-10:]
                
                # Stream LLM response using Ollama directly
                full_response = ""
                try:
                    async for chunk in stream_ollama_response(
                        conversation_history,
                        current_system_prompt
                    ):
                        full_response += chunk
                        await websocket.send_json({
                            "type": "text_chunk",
                            "chunk": chunk
                        })
                    
                    await websocket.send_json({
                        "type": "text_complete",
                        "full_text": full_response
                    })
                    
                    conversation_history.append({
                        "role": "assistant",
                        "content": full_response
                    })
                    
                except Exception as e:
                    logger.error(f"[{user_id}] LLM error: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"LLM error: {str(e)}"
                    })
            
            else:
                await websocket.send_json({
                    "type": "info",
                    "message": f"Text-only mode: {msg_type} not supported"
                })
                
    except WebSocketDisconnect:
        logger.info(f"[{user_id}] WebSocket disconnected (text-only mode)")


async def stream_ollama_response(
    messages: list[dict],
    system_prompt: str
):
    """Stream response from Ollama (text-only fallback)."""
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://10.0.0.15:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hf.co/TheBloke/Mythalion-13B-GGUF:Q4_K_M")
    
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
# Create app instance
app = create_app()

# Mount static files (must be last)
web_dir = Path("/app/web")
if not web_dir.exists():
    web_dir = Path(__file__).parent.parent.parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")


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
