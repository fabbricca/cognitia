"""
Cognitia Entrance - Main Server

This is the frontend-facing service that runs in Kubernetes:
- User authentication (JWT)
- Character/Chat CRUD (PostgreSQL)
- WebSocket proxy to GPU Core
- Static file serving for Web UI
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import UUID

import httpx
import websockets
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_user_id,
    hash_password,
    verify_password,
    verify_token,
    TokenPayload,
)
from .database import (
    init_db,
    get_session_dep,
    User,
    Character,
    Chat,
    Message,
)
from .schemas import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
    TokenRefresh,
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterListResponse,
    ChatCreate,
    ChatResponse,
    ChatListResponse,
    MessageCreate,
    MessageResponse,
    MessageListResponse,
    HealthResponse,
    ErrorResponse,
)


# Configuration
CORE_URL = os.getenv("COGNITIA_CORE_URL", "http://10.0.0.15:8080")
CORE_WS_URL = CORE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    await init_db()
    logger.info("Cognitia Entrance started")
    yield
    logger.info("Cognitia Entrance shutting down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="Cognitia Entrance",
        description="Authentication proxy for Cognitia AI assistant",
        version="3.0.0",
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    return app


app = create_app()


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["health"])
@app.get("/api/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    core_available = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{CORE_URL}/health")
            core_available = response.status_code == 200
    except Exception:
        pass
    
    return HealthResponse(core_available=core_available)


# =============================================================================
# Authentication Routes
# =============================================================================

@app.post("/api/auth/register", response_model=TokenResponse, tags=["auth"])
async def register(
    data: UserCreate,
    session: AsyncSession = Depends(get_session_dep),
):
    """Register a new user."""
    # Check if email exists
    result = await session.execute(
        select(User).where(User.email == data.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Create user
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
    )
    session.add(user)
    await session.flush()
    
    # Generate tokens
    access_token = create_access_token(user.id, user.email)
    refresh_token = create_refresh_token(user.id, user.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(
    data: UserLogin,
    session: AsyncSession = Depends(get_session_dep),
):
    """Login and get tokens."""
    result = await session.execute(
        select(User).where(User.email == data.email)
    )
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    access_token = create_access_token(user.id, user.email)
    refresh_token = create_refresh_token(user.id, user.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@app.post("/api/auth/refresh", response_model=TokenResponse, tags=["auth"])
async def refresh_token(
    data: TokenRefresh,
    session: AsyncSession = Depends(get_session_dep),
):
    """Refresh access token using refresh token."""
    payload = decode_token(data.refresh_token)
    
    if payload is None or payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    
    # Verify user still exists
    result = await session.execute(
        select(User).where(User.id == UUID(payload.sub))
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    access_token = create_access_token(user.id, user.email)
    refresh_token = create_refresh_token(user.id, user.email)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@app.get("/api/auth/me", response_model=UserResponse, tags=["auth"])
async def get_me(
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get current user info."""
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return UserResponse.model_validate(user)


@app.post("/api/auth/logout", tags=["auth"])
async def logout(
    user_id: UUID = Depends(get_user_id),
):
    """Logout current user (invalidate token client-side)."""
    # JWT tokens are stateless - client should discard the token
    # In a production system, you might want to blacklist the token
    return {"message": "Successfully logged out"}


# =============================================================================
# Character Routes
# =============================================================================

@app.get("/api/characters", response_model=CharacterListResponse, tags=["characters"])
@app.get("/api/characters/", response_model=CharacterListResponse, tags=["characters"], include_in_schema=False)
async def list_characters(
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """List all characters for the current user."""
    result = await session.execute(
        select(Character)
        .where(Character.user_id == user_id)
        .order_by(Character.created_at.desc())
    )
    characters = result.scalars().all()
    
    return CharacterListResponse(
        characters=[CharacterResponse.model_validate(c) for c in characters]
    )


@app.post("/api/characters", response_model=CharacterResponse, tags=["characters"])
@app.post("/api/characters/", response_model=CharacterResponse, tags=["characters"], include_in_schema=False)
async def create_character(
    data: CharacterCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Create a new character."""
    character = Character(
        user_id=user_id,
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        voice_model=data.voice_model,
        avatar_url=data.avatar_url,
    )
    session.add(character)
    await session.flush()
    await session.refresh(character)
    
    return CharacterResponse.model_validate(character)


@app.get("/api/characters/{character_id}", response_model=CharacterResponse, tags=["characters"])
async def get_character(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get a character by ID."""
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    return CharacterResponse.model_validate(character)


@app.put("/api/characters/{character_id}", response_model=CharacterResponse, tags=["characters"])
async def update_character(
    character_id: UUID,
    data: CharacterUpdate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Update a character."""
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    # Update fields
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(character, field, value)
    
    await session.flush()
    await session.refresh(character)
    
    return CharacterResponse.model_validate(character)


@app.delete("/api/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["characters"])
async def delete_character(
    character_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a character."""
    result = await session.execute(
        select(Character)
        .where(Character.id == character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    await session.delete(character)


# =============================================================================
# Chat Routes
# =============================================================================

@app.get("/api/chats", response_model=ChatListResponse, tags=["chats"])
@app.get("/api/chats/", response_model=ChatListResponse, tags=["chats"], include_in_schema=False)
async def list_chats(
    character_id: Optional[UUID] = None,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """List all chats for the current user, optionally filtered by character."""
    query = (
        select(Chat)
        .join(Character)
        .where(Character.user_id == user_id)
        .order_by(Chat.updated_at.desc())
    )
    
    if character_id:
        query = query.where(Chat.character_id == character_id)
    
    result = await session.execute(query)
    chats = result.scalars().all()
    
    return ChatListResponse(
        chats=[ChatResponse.model_validate(c) for c in chats]
    )


@app.post("/api/chats", response_model=ChatResponse, tags=["chats"])
@app.post("/api/chats/", response_model=ChatResponse, tags=["chats"], include_in_schema=False)
async def create_chat(
    data: ChatCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Create a new chat."""
    # Verify character belongs to user
    result = await session.execute(
        select(Character)
        .where(Character.id == data.character_id, Character.user_id == user_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    chat = Chat(
        character_id=data.character_id,
        title=data.title or f"Chat with {character.name}",
    )
    session.add(chat)
    await session.flush()
    await session.refresh(chat)
    
    return ChatResponse.model_validate(chat)


@app.get("/api/chats/{chat_id}", response_model=ChatResponse, tags=["chats"])
async def get_chat(
    chat_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Get a chat by ID."""
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    return ChatResponse.model_validate(chat)


@app.delete("/api/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["chats"])
async def delete_chat(
    chat_id: UUID,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Delete a chat."""
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    await session.delete(chat)


# =============================================================================
# Message Routes
# =============================================================================

@app.get("/api/chats/{chat_id}/messages", response_model=MessageListResponse, tags=["messages"])
async def list_messages(
    chat_id: UUID,
    limit: int = 50,
    offset: int = 0,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """List messages in a chat."""
    # Verify chat belongs to user
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    # Get messages
    result = await session.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit + 1)  # Fetch one extra to check if there's more
    )
    messages = list(result.scalars().all())
    
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]
    
    # Return in chronological order
    messages.reverse()
    
    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        has_more=has_more,
    )


@app.post("/api/chats/{chat_id}/messages", response_model=MessageResponse, tags=["messages"])
async def create_message(
    chat_id: UUID,
    data: MessageCreate,
    user_id: UUID = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_dep),
):
    """Create a message in a chat."""
    # Verify chat belongs to user
    result = await session.execute(
        select(Chat)
        .join(Character)
        .where(Chat.id == chat_id, Character.user_id == user_id)
    )
    chat = result.scalar_one_or_none()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )
    
    message = Message(
        chat_id=chat_id,
        role=data.role,
        content=data.content,
        audio_url=data.audio_url,
    )
    session.add(message)
    await session.flush()
    await session.refresh(message)
    
    return MessageResponse.model_validate(message)


# =============================================================================
# WebSocket Proxy to Core
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time communication.
    
    Flow:
    1. Client sends auth message with JWT
    2. After auth, messages are proxied to Core
    3. Core responses are proxied back to client
    
    Client messages:
    {"type": "auth", "token": "jwt..."}
    {"type": "text", "chatId": "...", "message": "..."}
    {"type": "audio", "chatId": "...", "data": "base64..."}
    {"type": "character_switch", "characterId": "..."}
    
    Server messages:
    {"type": "auth_success", "userId": "..."}
    {"type": "text_chunk", "content": "..."}
    {"type": "text_complete", "content": "..."}
    {"type": "audio", "content": "base64...", "sample_rate": 24000}
    {"type": "error", "message": "..."}
    """
    await websocket.accept()
    logger.info("WebSocket client connected")
    
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
        user_id = verify_token(token)
        
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
    
    # State
    current_character: Optional[Character] = None
    conversation_history: list[dict] = []
    
    # Try to connect to Core
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{CORE_URL}/health")
                core_available = response.status_code == 200
            except Exception:
                core_available = False
        
        if core_available:
            await websocket.send_json({
                "type": "status",
                "message": "Connected to AI core",
                "mode": "full"
            })
            await _proxy_to_core(websocket, user_id)
        else:
            await websocket.send_json({
                "type": "status",
                "message": "AI core not available. Text-only mode.",
                "mode": "text-only"
            })
            await _text_only_mode(websocket, user_id)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


async def _proxy_to_core(websocket: WebSocket, user_id: str):
    """Proxy WebSocket communication to Core."""
    from .database import get_session, Character, Chat, Message
    
    try:
        async with websockets.connect(CORE_WS_URL) as core_ws:
            async def forward_to_core():
                """Forward client messages to Core."""
                try:
                    while True:
                        msg = await websocket.receive_json()
                        msg_type = msg.get("type", "")
                        
                        if msg_type == "ping":
                            await websocket.send_json({"type": "pong"})
                            continue
                        
                        # Enrich message with context
                        msg["user_id"] = user_id
                        
                        if msg_type in ("text", "audio"):
                            # Get character info
                            char_id = msg.get("characterId")
                            chat_id = msg.get("chatId")
                            
                            if char_id:
                                async with get_session() as session:
                                    result = await session.execute(
                                        select(Character).where(Character.id == UUID(char_id))
                                    )
                                    char = result.scalar_one_or_none()
                                    if char:
                                        msg["system_prompt"] = char.system_prompt
                                        msg["model_id"] = str(char.id)
                                        msg["model_name"] = char.name
                                        msg["voice"] = char.voice_model
                                        msg["rvc_model_path"] = char.rvc_model_path
                                        msg["rvc_enabled"] = char.rvc_model_path is not None
                            
                            # Get conversation history
                            if chat_id:
                                async with get_session() as session:
                                    result = await session.execute(
                                        select(Message)
                                        .where(Message.chat_id == UUID(chat_id))
                                        .order_by(Message.created_at.desc())
                                        .limit(20)
                                    )
                                    messages = list(result.scalars().all())
                                    messages.reverse()
                                    msg["conversation_history"] = [
                                        {"role": m.role, "content": m.content}
                                        for m in messages
                                    ]
                        
                        # Map to Core format
                        core_msg = {
                            "type": "process",
                            "user_id": msg.get("user_id", user_id),
                            "model_id": msg.get("model_id", "default"),
                            "message": msg.get("message") or msg.get("data", ""),
                            "communication_type": msg_type if msg_type in ("text", "audio", "phone") else "text",
                            "system_prompt": msg.get("system_prompt", "You are a helpful AI assistant."),
                            "conversation_history": msg.get("conversation_history", []),
                            "model_name": msg.get("model_name", "Assistant"),
                            "voice": msg.get("voice", "af_bella"),
                            "rvc_model_path": msg.get("rvc_model_path"),
                            "rvc_enabled": msg.get("rvc_enabled", False),
                        }
                        
                        await core_ws.send(json.dumps(core_msg))
                        
                except WebSocketDisconnect:
                    pass
            
            async def forward_to_client():
                """Forward Core messages to client."""
                try:
                    async for message in core_ws:
                        data = json.loads(message)
                        await websocket.send_json(data)
                except Exception:
                    pass
            
            await asyncio.gather(
                forward_to_core(),
                forward_to_client(),
            )
            
    except Exception as e:
        logger.error(f"Core proxy error: {e}")
        await websocket.send_json({
            "type": "status",
            "message": f"Lost connection to AI core: {e}",
            "mode": "text-only"
        })
        await _text_only_mode(websocket, user_id)


async def _text_only_mode(websocket: WebSocket, user_id: str):
    """Handle text-only mode when Core is unavailable (direct Ollama fallback)."""
    from .database import get_session, Character, Message
    
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://10.0.0.15:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hf.co/bartowski/NousResearch_Hermes-4-14B-GGUF:latest")
    
    current_system_prompt = "You are a helpful AI assistant."
    conversation_history: list[dict] = []
    
    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            
            if msg_type == "character_switch":
                char_id = msg.get("characterId")
                if char_id:
                    async with get_session() as session:
                        result = await session.execute(
                            select(Character).where(Character.id == UUID(char_id))
                        )
                        char = result.scalar_one_or_none()
                        if char:
                            current_system_prompt = char.system_prompt
                            conversation_history = []
                            await websocket.send_json({
                                "type": "info",
                                "message": f"Switched to {char.name}"
                            })
            
            elif msg_type == "text":
                user_message = msg.get("message", "").strip()
                if not user_message:
                    continue
                
                conversation_history.append({"role": "user", "content": user_message})
                if len(conversation_history) > 20:
                    conversation_history = conversation_history[-20:]
                
                # Stream from Ollama
                full_response = ""
                try:
                    async for chunk in _stream_ollama(
                        conversation_history,
                        current_system_prompt,
                        OLLAMA_URL,
                        OLLAMA_MODEL,
                    ):
                        full_response += chunk
                        await websocket.send_json({
                            "type": "text_chunk",
                            "content": chunk
                        })
                    
                    await websocket.send_json({
                        "type": "text_complete",
                        "content": full_response
                    })
                    
                    conversation_history.append({
                        "role": "assistant",
                        "content": full_response
                    })
                    
                except Exception as e:
                    logger.error(f"LLM error: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"LLM error: {e}"
                    })
            
            elif msg_type == "audio":
                await websocket.send_json({
                    "type": "info",
                    "message": "Voice not available in text-only mode"
                })
            
    except WebSocketDisconnect:
        logger.info(f"Text-only mode disconnected: {user_id}")


async def _stream_ollama(
    messages: list[dict],
    system_prompt: str,
    ollama_url: str,
    ollama_model: str,
):
    """Stream response from Ollama."""
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    
    payload = {
        "model": ollama_model,
        "messages": full_messages,
        "stream": True,
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{ollama_url}/api/chat",
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


# =============================================================================
# Static Files (Web UI)
# =============================================================================

# Favicon
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


# Mount static files (must be last)
def _mount_static():
    """Mount static files directory."""
    # Try Docker path first, then local
    for web_dir in [Path("/app/web"), Path(__file__).parent.parent.parent.parent / "web"]:
        if web_dir.exists():
            app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")
            logger.info(f"Serving static files from {web_dir}")
            return
    logger.warning("No static files directory found")


_mount_static()


# =============================================================================
# CLI Entry Point
# =============================================================================

def run(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
):
    """Run the entrance server."""
    import uvicorn
    
    host = os.getenv("ENTRANCE_HOST", host)
    port = int(os.getenv("ENTRANCE_PORT", port))
    
    logger.info(f"Starting Cognitia Entrance on {host}:{port}")
    uvicorn.run(
        "cognitia.entrance.server:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    run()
